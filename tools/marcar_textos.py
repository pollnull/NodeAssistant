"""Envuelve en t() los textos fijos que ve el usuario (para traducirlos con tools/traducir.py).
Uso:  .venv\\Scripts\\python.exe tools\\marcar_textos.py archivo.py [--dry]
Busca textos en: lo que devuelve una función (lo que Node dice), show/notify/announce/tell/label/button,
text= de las ventanas, la descripción de los comandos y los textos de las tarjetas (ink).
Un f-string pasa a t('… {dato} …', dato=…), así el traductor ve la frase entera y los datos quedan aparte.
No toca: descripciones de herramientas y mensajes para la IA, direcciones, rutas ni palabras sueltas en minúscula
(esas se revisan a mano). Después, mira el diff: es una ayuda, no magia.
"""
import ast
import re
import sys
from pathlib import Path

CALLS = {'show', 'show_now', 'notify', 'announce', 'tell', 'label', 'put_in_pill'}  # su primer texto
SECOND = {'button', 'command', 'ink'}  # su segundo argumento
SKIP_FUNCTIONS = {'voice_url', 'raw_link', 'startup_command', 'plain', 'tidy', 'system', 'hint', 'problem',
                  'clean', 'file_name', 'when_text', 'at', 'credentials', 'build', 'report', 'check'}


def visible(text):
    """¿Parece un texto para una persona? (no una dirección, un código, una ruta ni una clave)."""
    text = text.strip()
    if not re.search(r'[A-Za-zÁÉÍÓÚáéíóúñÑ]{2}', text) or text.startswith(('http', '#', '/', '\\', '%', '{')):
        return False
    if re.fullmatch(r'[\w.\-:]+', text) and not re.match(r'[A-ZÁÉÍÓÚ¿¡]', text):  # una clave o un nombre de código
        return False
    return ' ' in text or text[:1] in '¿¡' or re.match(r'[A-ZÁÉÍÓÚ]', text) is not None


class Finder(ast.NodeVisitor):
    def __init__(self):
        self.found, self.function = [], []

    def visit_FunctionDef(self, node):
        self.function.append(node.name)
        self.generic_visit(node)
        self.function.pop()

    def take(self, value):
        """Los textos de una expresión (también dentro de x if y else z, a + b, a or b)."""
        if isinstance(value, ast.IfExp):
            self.take(value.body), self.take(value.orelse)
        elif isinstance(value, ast.BoolOp):
            [self.take(v) for v in value.values]
        elif isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
            self.take(value.left), self.take(value.right)
        elif isinstance(value, ast.Constant) and isinstance(value.value, str) and visible(value.value):
            self.found.append(value)
        elif isinstance(value, ast.JoinedStr):
            literal = ''.join(p.value for p in value.values if isinstance(p, ast.Constant))
            if visible(literal) or (literal.strip() and any(isinstance(p, ast.FormattedValue) for p in value.values)
                                    and re.search(r'[a-záéíóúñ]{3}', literal)):
                self.found.append(value)

    def visit_Return(self, node):
        if node.value is not None and not (self.function and self.function[-1] in SKIP_FUNCTIONS):
            self.take(node.value)
        self.generic_visit(node)

    def visit_Call(self, node):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
        if name in CALLS:
            for arg in node.args:
                if isinstance(arg, (ast.Constant, ast.JoinedStr, ast.IfExp, ast.BinOp)):
                    self.take(arg)
                    break
        elif name in SECOND and len(node.args) > 1:
            self.take(node.args[1])
        elif name in ('Label', 'Button', 'Checkbutton', 'Radiobutton', 'config', 'title', 'askopenfilename',
                      'askdirectory', 'append'):
            for keyword in node.keywords:
                if keyword.arg in ('text', 'title'):
                    self.take(keyword.value)
            if name in ('title', 'append') and node.args:
                self.take(node.args[0])
        self.generic_visit(node)


def placeholder(expr, source, used):
    if isinstance(expr, ast.Name):
        name = expr.id
    elif isinstance(expr, ast.Attribute):
        name = expr.attr
    elif isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant) and isinstance(expr.slice.value, str):
        name = expr.slice.value
    else:
        name = 'dato'
    name = re.sub(r'\W', '_', name).strip('_') or 'dato'
    if name[0].isdigit():
        name = 'v' + name
    base, number = name, 2
    while name in used and used[name] != source:
        name, number = f'{base}{number}', number + 1
    used[name] = source
    return name


def rewrite(node, text, prefix):
    if isinstance(node, ast.Constant):
        return f'{prefix}t({ast.unparse(ast.Constant(node.value))})'
    template, values, used = '', [], {}
    for part in node.values:
        if isinstance(part, ast.Constant):
            template += part.value.replace('{', '{{').replace('}', '}}')
            continue
        source = ast.get_source_segment(text, part.value) or ast.unparse(part.value)
        if part.format_spec is not None:
            spec = ast.unparse(part.format_spec)[2:-1]  # f'...'
            source = f'format({source}, {spec!r})'
        if part.conversion == ord('r'):
            source = f'repr({source})'
        name = placeholder(part.value, source, used)
        template += '{' + name + '}'
        if (name, source) not in values:
            values.append((name, source))
    args = ', '.join(f'{name}={source}' for name, source in values)
    return f'{prefix}t({template!r}{", " + args if args else ""})'


def main():
    path, dry = Path(sys.argv[1]), '--dry' in sys.argv
    text = path.read_text(encoding='utf-8')
    finder = Finder()
    finder.visit(ast.parse(text))
    prefix = '' if path.name == 'node_assistant.py' else 'node.'
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for found in finder.found:
        start = offsets[found.lineno - 1] + len(lines[found.lineno - 1][:found.col_offset].encode('utf-8')
                                                .decode('utf-8'))
        end = offsets[found.end_lineno - 1] + found.end_col_offset
        # col_offset es en bytes UTF-8: se convierte a caracteres
        start = offsets[found.lineno - 1] + len(lines[found.lineno - 1].encode('utf-8')[:found.col_offset]
                                                .decode('utf-8'))
        end = offsets[found.end_lineno - 1] + len(lines[found.end_lineno - 1].encode('utf-8')[:found.end_col_offset]
                                                  .decode('utf-8'))
        original = text[start:end]
        if re.match(r'(node\.)?t\(', text[max(0, start - 7):start].split()[-1] if text[max(0, start - 7):start].split()
                    else ''):
            continue
        edits.append((start, end, original, rewrite(found, text, prefix)))
    for start, end, original, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    for _, _, original, new in sorted(edits):
        print(f'- {original[:100]!s}\n+ {new[:140]}\n')
    print(f'{len(edits)} textos en {path.name}')
    if not dry:
        compile(text, str(path), 'exec')
        path.write_text(text, encoding='utf-8', newline='\n')  # LF, como el resto del repo


if __name__ == '__main__':
    main()

"""Small, conservative reader for the instruction syntax used by the reference setup.

Imports are expanded in order. Unsupported block nesting fails explicitly. Original
source files are retained separately; generated model instructions are flattened.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import shlex

class ConfigError(ValueError):
    pass


def uncomment(line):
    quote = None
    result = []
    for char in line:
        if char in "\"'":
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        if char == '!' and quote is None:
            break
        result.append(char)
    return ''.join(result)


def words(text):
    return shlex.split(text, posix=True)


def balance(text):
    text = re.sub(r'"[^"\n]*"|\'[^\'\n]*\'', '', text)
    return text.count('(') - text.count(')')


@dataclass
class Node:
    text: str
    source: Path
    line: int
    kind: str = ''
    name: str = ''

    @property
    def clean(self):
        return '\n'.join(uncomment(x) for x in self.text.splitlines()).strip()


def parse_file(path):
    path = Path(path)
    lines = path.read_text(encoding='utf-8-sig').splitlines(keepends=True)
    nodes = []
    i = 0
    while i < len(lines):
        start = i
        text = lines[i]
        depth = balance(uncomment(text))
        i += 1
        while depth > 0 and i < len(lines):
            text += lines[i]
            depth += balance(uncomment(lines[i]))
            i += 1
        if depth != 0:
            raise ConfigError(f'{path}:{start+1}: unbalanced parentheses')
        clean = '\n'.join(uncomment(x) for x in text.splitlines()).strip()
        match = re.match(r'^(group|pft|st|mt)\s+["\']([^"\']+)["\']\s*\(', clean)
        node = Node(text, path, start + 1)
        if match:
            node.kind, node.name = match.groups()
        elif clean.startswith('import '):
            node.kind = 'import'
            tokens = words(clean)
            if len(tokens) != 2:
                raise ConfigError(f'{path}:{start+1}: malformed import')
            node.name = tokens[1]
        nodes.append(node)
    return nodes


class Instructions:
    def __init__(self, main):
        self.main = Path(main).resolve()
        self.files = {}
        self.nodes = []
        self._expand(self.main, [])
        self.definitions = {}
        self.globals = {}
        self.params = {}
        for node in self.nodes:
            if node.kind in ('group', 'pft', 'st', 'mt'):
                self.definitions.setdefault((node.kind, node.name), []).append(node)
            elif node.clean:
                tokens = words(node.clean)
                if tokens and tokens[0] == 'param':
                    match = re.fullmatch(r'param\s+["\']([^"\']+)["\']\s*\(\s*str\s+["\']([^"\']*)["\']\s*\)', node.clean)
                    if match:
                        self.params[match[1]] = (match[2], node.source.parent)
                elif tokens:
                    self.globals[tokens[0]] = tokens[1:]

    def _expand(self, path, stack):
        path = path.resolve()
        if path in stack:
            raise ConfigError('Import cycle: ' + ' -> '.join(map(str, stack + [path])))
        if not path.is_file():
            raise ConfigError(f'Missing instruction file: {path}')
        self.files[path] = path.read_text(encoding='utf-8-sig')
        for node in parse_file(path):
            if node.kind == 'import':
                self._expand(path.parent / node.name, stack + [path])
            else:
                self.nodes.append(node)

    def resolve(self, kind, name, stack=()):
        key = (kind, name)
        if key in stack:
            raise ConfigError(f'Group inheritance cycle: {stack + (key,)}')
        if key not in self.definitions:
            raise ConfigError(f'Undefined {kind} {name}')
        result = {}
        for node in self.definitions[key]:
            clean = node.clean
            body = clean[clean.index('(')+1:clean.rfind(')')]
            if balance(body) or '(' in re.sub(r'"[^"]*"', '', body):
                raise ConfigError(f'Nested block unsupported: {kind} {name}')
            for line in body.splitlines():
                tokens = words(line)
                if not tokens:
                    continue
                if len(tokens) == 1:
                    result.update(self.resolve('group', tokens[0], stack + (key,)))
                else:
                    result[tokens[0]] = tokens[1:]
        return result

    def scalar(self, name, default=None):
        values = self.globals.get(name)
        return values[0] if values else default

    def flatten(self, omit=(), relocate_inputs=True):
        chunks = []
        for node in self.nodes:
            if (node.kind, node.name) in omit:
                continue
            text = node.text
            # Resolve relative environmental paths before moving the instructions.
            # Output paths are globals, not these param/file_* string records.
            match = re.fullmatch(r'param\s+["\'](file_[^"\']+)["\']\s*\(\s*str\s+["\']([^"\']*)["\']\s*\)', node.clean)
            if relocate_inputs and match and match[2] and not match[2].startswith(('/', '$')) and not re.match(r'^[A-Za-z]:', match[2]):
                value = (node.source.parent / match[2]).resolve().as_posix()
                text = f'param "{match[1]}" (str "{value}")\n'
            chunks.append(text.rstrip() + '\n')
        return ''.join(chunks)


def block(kind, name, values):
    lines = [f'{kind} "{name}" (']
    for key, value in values.items():
        if isinstance(value, str):
            if any(c in value for c in ('"', '\n', '\r')):
                raise ConfigError(f'Unsafe instruction string: {key}')
            value = f'"{value}"'
        lines.append(f'    {key} {value}')
    return '\n'.join(lines + [')', ''])

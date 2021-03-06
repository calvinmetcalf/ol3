#!/usr/bin/env python

from collections import defaultdict
from itertools import ifilter
from operator import attrgetter
from optparse import OptionParser
import re
import sys


def simplerepr(obj):
    keys = sorted(key for key in obj.__dict__.keys() if not key.startswith('_'))
    attrs = ''.join(' %s=%r' % (key, obj.__dict__[key]) for key in keys)
    return '<%s%s>' % (obj.__class__.__name__, attrs)


class Exportable(object):

    def __init__(self, name):
        self.name = name

    __repr__ = simplerepr

    def export(self):
        return ''

    def extern(self):
        return ''

    def typedef(self):
        return ''


class Class(Exportable):

    def __init__(self, name, object_literal, objects):
        Exportable.__init__(self, name)
        self.object_literal = object_literal
        self.objects = objects
        self.props = set()

    __repr__ = simplerepr

    def nested_options(self):
        def get_class_by_object_literal_name(name):
            for k, o in self.objects.iteritems():
                if isinstance(o, Class) and o.object_literal.name == name:
                    return o
            return None

        for option in sorted(self.object_literal.prop_types.keys()):
            types = self.object_literal.prop_types[option].split('|')
            base, object_literal = None, None
            for t in types:
                if t in self.objects:
                    o = self.objects[t]
                    if isinstance(o, (Class, Symbol)):
                        if base:
                            raise RuntimeError('Multiple "class" types found for '
                                'option %s.%s: %s, %s.' %
                                (self.object_literal.name, option,
                                 base.name, o.name))
                        base = o
                    elif isinstance(o, ObjectLiteral):
                        if object_literal:
                            raise RuntimeError('Multiple "literal" types found for '
                                'option %s.%s: %s, %s.' %
                                (self.object_literal.name, option,
                                 object_literal.name, o.name))
                        object_literal = o
            if object_literal:
                if not base:
                    raise RuntimeError('%s "literal" type found for option %s.%s, '
                        'but no "class" type.' %
                        (object_literal.name, self.object_literal.name, option))
                klass = get_class_by_object_literal_name(object_literal.name)
                if not klass:
                    raise RuntimeError('No constructor taking a %s found.' %
                        object_literal.name)
                yield option, object_literal, klass, base

    def export(self):
        lines = []
        if self.object_literal is None:
            lines.append('\n\ngoog.exportSymbol(\n    \'%s\',\n    %s);\n' % (self.name, self.name))
        else:
            lines.append('\n\n\n')
            lines.append('/**\n')
            lines.append(' * @constructor\n')
            lines.append(' * @extends {%s}\n' % (self.name,))
            lines.append(' * @param {%s} options Options.\n' % (self.object_literal.extern_name(),))
            lines.append(' */\n')
            lines.append('%s = function(options) {\n' % (self.export_name(),))
            lines.append('  /** @type {%s} */\n' % (self.object_literal.name,))
            lines.append('  var arg;\n');
            lines.append('  if (goog.isDefAndNotNull(options)) {\n')
            # FIXME: we modify the user's options object
            lines.append(''.join(
                         '    if (!(options.%(o)s instanceof %(base)s)) {\n'
                         '      options.%(o)s = new %(ctor)s(\n'
                         '          /** @type {%(extern)s} */ (options.%(o)s));\n'
                         '    }\n' %
                             {'o': o, 'base': b.name, 'ctor': k.export_name(),
                              'extern': ol.extern_name()} \
                                     for o, ol, k, b in self.nested_options()))
            lines.append('    arg = {')
            lines.extend(','.join('\n      %s: options.%s' % (key, key) for key in sorted(self.object_literal.prop_types.keys())))
            lines.append('\n    };\n')
            lines.append('  } else {\n')
            lines.append('    arg = /** @type {%s} */ (options);\n' % (self.object_literal.name,))
            lines.append('  }\n')
            lines.append('  goog.base(this, arg);\n')
            lines.append('};\n')
            lines.append('goog.inherits(%sExport, %s);\n' % (self.name, self.name))
            lines.append('goog.exportSymbol(\n')
            lines.append('    \'%s\',\n' % (self.name,))
            lines.append('    %s);\n' % (self.export_name(),))
        lines.extend('goog.exportProperty(\n    %s,\n    \'%s\',\n    %s.%s);\n' % (self.name, prop, self.name, prop) for prop in sorted(self.props))
        return ''.join(lines)

    def export_name(self):
        return '%sExport' % self.name


class ObjectLiteral(Exportable):

    def __init__(self, name):
        Exportable.__init__(self, name)
        self.prop_types = {}

    __repr__ = simplerepr

    def extern(self):
        lines = []
        lines.append('\n\n\n')
        lines.append('/**\n')
        lines.append(' * @interface\n')
        lines.append(' */\n')
        lines.append('%s = function() {};\n' % (self.extern_name(),))
        for prop in sorted(self.prop_types.keys()):
            lines.append('\n\n')
            lines.append('/**\n')
            lines.append(' * @type {%s}\n' % (self.prop_types[prop],))
            lines.append(' */\n')
            lines.append('%s.prototype.%s;\n' % (self.extern_name(), prop))
        return ''.join(lines)

    def extern_name(self):
        return re.sub(r'ol\.(\S+)', r'olx.\1Extern', self.name)

    def extern_namespace(self):
        return '.'.join(self.extern_name().split('.')[:-1]) or None

    def provide(self):
        return 'goog.provide(\'%s\');\n' % (self.name,)

    def typedef(self):
        lines = []
        lines.append('\n\n')
        lines.append('/**\n')
        for i, prop in enumerate(sorted(self.prop_types.keys())):
            prefix =  ' * @typedef {{' if i == 0 else ' *            '
            suffix = '}}' if i == len(self.prop_types) - 1 else ','
            type = self.prop_types[prop]
            if '|' in type:
                type = '(%s)' % (type,)
            lines.append('%s%s: %s%s\n' % (prefix, prop, type, suffix))
        lines.append(' */\n')
        lines.append('%s;\n' % (self.name,))
        return ''.join(lines)


class Symbol(Exportable):

    def __init__(self, name, export_symbol, export_as=None):
        Exportable.__init__(self, name)
        self.export_symbol = export_symbol
        self.export_as = export_as or self.name
        self.props = set()

    __repr__ = simplerepr

    def export(self):
        lines = []
        if self.export_symbol:
            lines.append('\n\ngoog.exportSymbol(\n    \'%s\',\n    %s);\n' % (self.name, self.export_as))
        lines.extend('goog.exportProperty(\n    %s,\n    \'%s\',\n    %s.%s);\n' % (self.name, prop, self.name, prop) for prop in sorted(self.props))
        return ''.join(lines)


def main(argv):

    option_parser = OptionParser()
    option_parser.add_option('--exports', action='store_true')
    option_parser.add_option('--externs', action='store_true')
    option_parser.add_option('--typedef', action='store_true')
    options, args = option_parser.parse_args(argv[1:])

    objects = {}
    requires = set()
    for arg in args:
        in_comment = False
        object_literal = None
        for line in open(arg):
            line = line.strip()
            if not line:
                continue
            if line == '/**':
                assert not in_comment
                in_comment = True
                continue
            if line == '*/':
                assert in_comment
                in_comment = False
                object_literal = None
                continue
            if in_comment:
                if not line.startswith('*'):
                    raise RuntimeError(line)  # malformed comment
                m = re.match(r'\*\s*@typedef\s*\{Object\}\s*(?P<name>\S+)', line)
                if m:
                    assert object_literal is None
                    name = m.group('name')
                    if name in objects:
                        raise RuntimeError(line)  # Name already defined
                    object_literal = ObjectLiteral(name)
                    objects[name] = object_literal
                    continue
                m = re.match(r'\*\s*@property\s*{(?P<type>.*)}\s*(?P<prop>\S+)', line)
                if m:
                    assert object_literal is not None
                    prop = m.group('prop')
                    if prop in object_literal.prop_types:
                        raise RuntimeError(line)  # Duplicate property
                    type = m.group('type')
                    object_literal.prop_types[prop] = type
                    continue
                continue
            m = re.match(r'@exportClass\s+(?P<name>\S+)(?:\s+(?P<object_literal_name>\S+))?\Z', line)
            if m:
                name = m.group('name')
                if name in objects:
                    raise RuntimeError(line)  # Name already defined
                object_literal_name = m.group('object_literal_name')
                object_literal = objects[object_literal_name]
                if not isinstance(object_literal, ObjectLiteral):
                    raise RuntimeError(line)  # Undefined object literal
                klass = Class(name, object_literal, objects)
                objects[name] = klass
                continue
            m = re.match(r'@exportProperty\s+(?P<prop>\S+)\Z', line)
            if m:
                components = m.group('prop').split('.')
                if components[-2] == 'prototype':
                    requires.add('.'.join(components[:-2]))
                else:
                    requires.add('.'.join(components[:-1]))
                name = '.'.join(components[:-1]) 
                prop = components[-1]
                if name in objects:
                    symbol = objects[name]
                else:
                    symbol = Symbol(name, False)
                    objects[name] = symbol
                symbol.props.add(prop)
                continue
            m = re.match(r'@exportSymbol\s+(?P<name>\S+)(?:\s+(?P<export_as>\S+))?\Z', line)
            if m:
                name = m.group('name')
                if name in objects:
                    raise RuntimeError(line)  # Name already defined
                export_as = m.group('export_as')
                symbol = Symbol(name, True, export_as)
                objects[name] = symbol
                if not export_as:
                    components = m.group('name').split('.')
                    if re.match(r'[A-Z]', components[-1]):
                        requires.add(name)
                    elif len(components) > 2:
                        requires.add('.'.join(components[:-1]))
                continue
            raise RuntimeError(line)

    objects = sorted(objects.values(), key=attrgetter('name'))

    if options.exports:
        requires.update(obj.name for obj in objects if isinstance(obj, Class))
        if requires:
            for require in sorted(requires):
                sys.stdout.write('goog.require(\'%s\');\n' % (require,))
        for obj in objects:
            sys.stdout.write(obj.export())

    if options.externs:
        object_literals = [obj for obj in objects if isinstance(obj, ObjectLiteral)]
        sys.stdout.write('/**\n')
        sys.stdout.write(' * @externs\n')
        sys.stdout.write(' */\n')
        namespaces = sorted(set(filter(None, (object_literal.extern_namespace() for object_literal in object_literals))))
        for namespace in namespaces:
            sys.stdout.write('\n\n')
            sys.stdout.write('/**\n')
            sys.stdout.write(' * @type {Object}\n')
            sys.stdout.write(' */\n')
            if '.' in namespace:
                sys.stdout.write('%s = {};\n' % (namespace,))
            else:
                sys.stdout.write('var %s;\n' % (namespace,))
        for object_literal in object_literals:
            sys.stdout.write(object_literal.extern())

    if options.typedef:
        object_literals = [obj for obj in objects if isinstance(obj, ObjectLiteral)]
        for object_literal in object_literals:
            sys.stdout.write(object_literal.provide())
        for object_literal in object_literals:
            sys.stdout.write(object_literal.typedef())


if __name__ == '__main__':
    sys.exit(main(sys.argv))

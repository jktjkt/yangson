# Copyright © 2019 Telecom Infra Project
# Written by Jan Kundrát <jkt@flaska.net>
#
# This file is part of Yangson.
#
# Yangson is free software: you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# Yangson is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with Yangson.  If not, see <http://www.gnu.org/licenses/>.

"""This module defines the entry point for a script which generates a JSON Schema."""

import argparse
import copy
import json
import os
import sys
import pkg_resources
from typing import List
from yangson import DataModel
from yangson import schemanode, datatype
from yangson.exceptions import (
    BadYangLibraryData, FeaturePrerequisiteError, MultipleImplementedRevisions,
    ModuleNotFound, ModuleNotRegistered, RawMemberError, RawTypeError,
    SchemaError, SemanticError, YangTypeError)

def debug_walk_string(node, indent: str = ""):
    for child in node.children:
        if isinstance(child, schemanode.GroupNode):
            print(f'{indent}[group]')
        else:
            print(f'{indent}{child.iname()} {child}')
        if not isinstance(child, schemanode.TerminalNode):
            debug_walk_string(child, indent + "  ")

def jsonschema_type_from_class(nodetype):
    if isinstance(nodetype, datatype.BooleanType):
        return 'boolean'
    if isinstance(nodetype, datatype.Int8Type) \
        or isinstance(nodetype, datatype.Int16Type) \
        or isinstance(nodetype, datatype.Int32Type) \
        or isinstance(nodetype, datatype.Int64Type) \
        or isinstance(nodetype, datatype.Uint8Type) \
        or isinstance(nodetype, datatype.Uint16Type) \
        or isinstance(nodetype, datatype.Uint32Type) \
        or isinstance(nodetype, datatype.Uint64Type) \
        or isinstance(nodetype, datatype.Decimal64Type):
        return 'number'
    else:
        return 'string'

def walk_json_schema(node, parent_level_data: dict = None):
    if isinstance(node, schemanode.TerminalNode):
        parent_level_data['properties'][node.iname()] = {
        'description': node.description,
        }
        if node.mandatory:
            parent_level_data['required'].append(node.iname())
        if isinstance(node, schemanode.LeafNode):
            parent_level_data['properties'][node.iname()]['type'] = jsonschema_type_from_class(node.type)
        return parent_level_data


    # now we know we have children
    if parent_level_data is None:
        parent_level_data = {
            'type': 'object',
            'properties': {},
            'required': [],
            '$schema': 'http://json-schema.org/draft-04/schema#',
        }

    children_data = {
        'properties': {},
        'type': 'object',
        'description': node.description,
        'required': [],
        }

    if isinstance(node, schemanode.ChoiceNode):
        # we're introducing an extra level here for a reasonable JSON UI functionality
        fake_node_name = f'_choice:{node.iname()}'
        cases = []
        for child in node.children:
            blank = copy.copy(children_data)
            new_node = walk_json_schema(child, blank)
            new_node['title'] = child.iname()
            new_node['additionalProperties'] = False
            new_node['required'] = [x.iname() for x in child.children]
            cases.append(new_node)
        parent_level_data['properties'][fake_node_name] = {
            'title': node.description,
            'oneOf': cases,
            'additionalProperties': False,
        }
        if node.mandatory:
            parent_level_data['required'].append(fake_node_name)
        return parent_level_data

    for child in node.children:
        if node.name is None and child.qual_name[1] != 'tip-photonic-equipment':
            continue
        children_data = walk_json_schema(child, children_data)


    if isinstance(node, schemanode.GroupNode) or \
            isinstance(node, schemanode.ChoiceNode) or \
            isinstance(node, schemanode.CaseNode):
        # do not introduce an extra node here
        parent_level_data['properties'].update(children_data['properties'])
        parent_level_data['required'] += children_data['required'] if hasattr(children_data, 'required') else []
    else:
        parent_level_data['properties'][node.iname()] = children_data

    if isinstance(node, schemanode.ChoiceNode):
        # FIXME: this assumes that there's always a single top-level container in each `case` branch
        # FIXME: and also that there's always at most one choice in each level...
        all_real_children = [grandchild for child in node.children for grandchild in child.children if isinstance(child, schemanode.CaseNode)]
        #parent_level_data['oneOf'] = [{'required': [x.iname()]} for x in all_real_children]

    return parent_level_data

#walk = debug_walk_string
def walk(node): print(json.dumps(walk_json_schema(node), indent=2))


def main(ylib: str = None, path: str = None) -> int:
    """Convert a YANG file into a JSON Schema.

    Args:
        ylib: Name of the file with YANG library
        path: Colon-separated list of directories to search  for YANG modules.

    Returns:
        Numeric return code (0=no error, 2=YANG error, 1=other)
    """
    if ylib is None:
        parser = argparse.ArgumentParser(
            prog="yangson-json-schema",
            description="Generate a JSON Schema for a YANG data model.")
        parser.add_argument(
            "-V", "--version", action="version",
            version=f"%(prog)s {pkg_resources.get_distribution('yangson').version}")
        parser.add_argument(
            "ylib", metavar="YLIB",
            help=("name of the file with description of the data model"
                  " in JSON-encoded YANG library format [RFC 7895]"))
        parser.add_argument(
            "-p", "--path",
            help=("colon-separated list of directories to search"
                  " for YANG modules"))
        args = parser.parse_args()
        ylib: str = args.ylib
        path: Optional[str] = args.path
    try:
        with open(ylib, encoding="utf-8") as infile:
            yl = infile.read()
    except (FileNotFoundError, PermissionError,
            json.decoder.JSONDecodeError) as e:
        print("YANG library:", str(e), file=sys.stderr)
        return 1
    sp = path if path else os.environ.get("YANG_MODPATH", ".")
    try:
        dm = DataModel(yl, tuple(sp.split(":")))
    except BadYangLibraryData as e:
        print("Invalid YANG library:", str(e), file=sys.stderr)
        return 2
    except FeaturePrerequisiteError as e:
        print("Unsupported pre-requisite feature:", str(e), file=sys.stderr)
        return 2
    except MultipleImplementedRevisions as e:
        print("Multiple implemented revisions:", str(e), file=sys.stderr)
        return 2
    except ModuleNotFound as e:
        print("Module not found:", str(e), file=sys.stderr)
        return 2
    except ModuleNotRegistered as e:
        print("Module not registered:", str(e), file=sys.stderr)
        return 2

    walk(dm.schema)
    return 0

if __name__ == "__main__":
    sys.exit(main())

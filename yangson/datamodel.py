# Copyright © 2016-2019 CZ.NIC, z. s. p. o.
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

"""Basic access to the Yangson library.

This module implements the following class:

* DataModel: Basic entry point to the YANG data model.
"""

import hashlib
import json
from typing import Dict, Optional, Tuple
from .enumerations import ContentType
from .exceptions import BadYangLibraryData
from .instance import (InstanceRoute, InstanceIdParser, ResourceIdParser,
                       RootNode)
from .schemadata import SchemaData, SchemaContext
from .schemanode import DataNode, SchemaTreeNode, RawObject, SchemaNode
from .typealiases import DataPath, SchemaPath, YangIdentifier


class Datastore:
    """Container for a datastore schema.
    
    Attributes:
        schema: Root of the schema tree.
        content_type: Content type of the datastore.
    """
    content_type: ContentType
    schema: SchemaTreeNode
    schema_data: SchemaData

    def __init__(self, schema: SchemaTreeNode, schema_data: SchemaData,
                 content_type: ContentType = ContentType.config):
        """Initialize the class instance."""
        self.content_type = content_type
        self.schema_data = schema_data
        self.schema = schema

    def from_raw(self, robj: RawObject) -> RootNode:
        """Create an instance node from a raw data tree.

        Args:
            robj: Dictionary representing a raw data tree.

        Returns:
            Root instance node.
        """
        cooked = self.schema.from_raw(robj)
        return RootNode(cooked, self.schema, cooked.timestamp)

    def get_schema_node(self, path: SchemaPath) -> Optional[SchemaNode]:
        """Return the schema node addressed by a schema path.

        Args:
            path: Schema path.

        Returns:
            Schema node if found in the schema, or ``None``.

        Raises:
            InvalidSchemaPath: If the schema path is invalid.
        """
        return self.schema.get_schema_descendant(
            self.schema_data.path2route(path))

    def get_data_node(self, path: DataPath) -> Optional[DataNode]:
        """Return the data node addressed by a data path.

        Args:
            path: Data path.

        Returns:
            Data node if found in the schema, or ``None``.

        Raises:
            InvalidSchemaPath: If the schema path is invalid.
        """
        addr = self.schema_data.path2route(path)
        node = self.schema
        for p in addr:
            node = node.get_data_child(*p)
            if node is None:
                return None
        return node

    def ascii_tree(self, no_types: bool = False) -> str:
        """Generate ASCII art representation of the schema tree.

        Args:
            no_types: Suppress output of data type info.

        Returns:
            String with the ASCII tree.
        """
        return self.schema.ascii_tree("", no_types)

    @staticmethod
    def parse_instance_id(text: str) -> InstanceRoute:
        return InstanceIdParser(text).parse()

    def parse_resource_id(self, text: str) -> InstanceRoute:
        return ResourceIdParser(text, self.schema).parse()

    def schema_digest(self) -> str:
        """Generate schema digest (to be used primarily by clients).

        Returns:
            Condensed information about the schema in JSON format.
        """
        res = self.schema.node_digest()
        res["config"] = True
        return json.dumps(res)


class DataModel:
    """Basic user-level entry point to Yangson library.

    Attributes:
        datastores: Dictionary of available datastore schemas.
        yang_library: YANG library object.
    """
    datastores: Dict[YangIdentifier, Datastore]
    description: str
    yang_library: Dict[YangIdentifier, Dict]

    @classmethod
    def from_file(cls, name: str, mod_path: Tuple[str, ...] = (".",),
                  description: str = None) -> "DataModel":
        """Initialize the data model from a file with YANG library data.

        Args:
            name: Name of a file with YANG library data.
            mod_path: Tuple of directories where to look for YANG modules.
            description:  Optional description of the data model.

        Returns:
            The data model instance.

        Raises:
            The same exceptions as the class constructor.
        """

        with open(name, encoding="utf-8") as infile:
            yltxt = infile.read()
        return cls(yltxt, mod_path, description)

    def __init__(self, yltxt: str, mod_path: Tuple[str, ...] = (".",),
                 description: str = None):
        """Initialize the class instance.

        Args:
            yltxt: JSON text with YANG library data.
            mod_path: Tuple of directories where to look for YANG modules.
            description: Optional description of the data model.

        Raises:
            BadYangLibraryData: If YANG library data is invalid.
            FeaturePrerequisiteError: If a pre-requisite feature isn't
                supported.
            MultipleImplementedRevisions: If multiple revisions of an
                implemented module are listed in YANG library.
            ModuleNotFound: If a YANG module wasn't found in any of the
                directories specified in `mod_path`.
        """
        self.datastores = {}
        self.description = description
        try:
            self.yang_library = json.loads(yltxt)
        except json.JSONDecodeError as e:
            raise BadYangLibraryData(str(e)) from None
        if "ietf-yang-library:modules-state" in self.yang_library:  # RFC 7895
            root = SchemaTreeNode()
            sdata = SchemaData(self.yang_library, mod_path)
            self._build_schema(root, sdata)
            self.datastores["config"] = Datastore(root, sdata)
            self.datastores["operational"] = Datastore(root, sdata, ContentType.all)
        else:
            raise BadYangLibraryData("top-level member not recognized")

    def content_id(self) -> str:
        """Compute unique id of the data model.

        Returns:
            String consisting of hexadecimal digits.
        """
        # return hashlib.sha1("".join(fnames).encode("ascii")).hexdigest()
        return "TODO"

    @staticmethod
    def _build_schema(schema: SchemaTreeNode, schema_data: SchemaData) -> None:
        for mid in schema_data.module_sequence:
            sctx = SchemaContext(schema_data, schema_data.namespace(mid), mid)
            schema.handle_substatements(schema_data.modules[mid].statement, sctx)
        for mid in schema_data.module_sequence:
            sctx = SchemaContext(schema_data, schema_data.namespace(mid), mid)
            mod = schema_data.modules[mid].statement
            for aug in mod.find_all("augment"):
                schema.augment_stmt(aug, sctx)
        schema.post_process()
        schema.make_schema_patterns()

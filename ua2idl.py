from __future__ import print_function
from collections import OrderedDict
import re
from lxml import etree
import argparse

builtin_types = ["Boolean", "SByte", "Byte", "Int16", "UInt16",
                 "Int32", "UInt32", "Int64", "UInt64", "Float",
                 "Double", "String", "DateTime", "Guid", "ByteString",
                 "XmlElement", "NodeId", "ExpandedNodeId", "StatusCode",
                 "QualifiedName", "LocalizedText", "ExtensionObject", "DataValue",
                 "Variant", "DiagnosticInfo"]

# empty structs are not allowed in IDL
skip_types = ["FilterOperand", "HistoryReadDetails", "MonitoringFilter",
              "MonitoringFilterResult", "NotificationData"]

# idl keywords are prefixed with a "_"
idl_keywords = ["abstract", "exception", "inout", "provides", "truncatable",
                "any", "emits", "interface", "public", "typedef", "attribute",
                "enum", "local", "publishes", "typeid", "boolean", "eventtype",
                "long", "raises", "typeprefix", "case", "factory", "module", "readonly",
                "unsigned", "char", "FALSE", "multiple", "setraises", "union", "component",
                "finder", "native", "sequence", "uses", "const", "fixed", "Object", "short",
                "ValueBase", "consumes", "float", "octet", "string", "valuetype", "context",
                "getraises", "oneway", "struct", "void", "custom", "home", "out", "supports",
                "wchar", "default", "import", "primarykey", "switch", "wstring", "double", "in",
                "private", "TRUE"]

def protected_identifier(s):
    if s in idl_keywords:
        return "_" + s
    return s

class Type(object):
    def __init__(self, name, description = ""):
        self.name = name
        self.description = description

    def typedef_idl(self):
        pass
    
class BuiltinType(Type):
    pass

class EnumerationType(Type):
    def __init__(self, name, description = "", elements = OrderedDict()):
        self.name = protected_identifier(name)
        self.description = description
        self.elements = elements # maps a name to an integer value

    def typedef_idl(self):
        tdef = "\tenum " + self.name + " {\n"
        for el in self.elements:
            tdef += "\t\t" + protected_identifier(el) + ", \n"
        return tdef[:-3] + "\n\t};"

class OpaqueType(Type):
    def typedef_idl(self):
        return "\ttypedef ByteString " + protected_identifier(self.name) + ";"

class StructMember(object):
    def __init__(self, name, memberType, isArray):
        self.name = protected_identifier(name)
        self.memberType = protected_identifier(memberType)
        self.isArray = isArray

class StructType(Type):
    def __init__(self, name, description, members = OrderedDict()):
        self.name = protected_identifier(name)
        self.description = description
        self.members = members # maps a name to a member definition

    def typedef_idl(self):
        tdef = "\t struct " + self.name + " {\n"
        for member in self.members.values():
            if member.isArray:
                tdef += "\t\tListOf" + member.memberType.name + " " + member.name + ";\n"
            else:
                tdef += "\t\t" + member.memberType.name + " " + member.name + ";\n"
        return tdef + "\t};"

def parseTypeDefinitions(xmlDescription):
    '''Returns an ordered dict that maps names to types. The order is such that
       every type depends only on known types. '''
    ns = {"opc": "http://opcfoundation.org/BinarySchema/"}
    tree = etree.parse(xmlDescription)
    typeSnippets = tree.xpath("/opc:TypeDictionary/*[not(self::opc:Import)]", namespaces=ns)
    types = OrderedDict()
    for t in builtin_types:
        types[t] = BuiltinType(t)

    # types we do not want to autogenerate
    def skipType(name):
        if name in builtin_types:
            return True
        if name in skip_types:
            return True
        if "Test" in name: # skip all test types
            return True
        if re.search("NodeId$", name) != None:
            return True
        return False

    def stripTypename(tn):
        return tn[tn.find(":")+1:]

    def typeReady(element):
        "Do we have the member types yet?"
        for child in element:
            if child.tag == "{http://opcfoundation.org/BinarySchema/}Field":
                if stripTypename(child.get("TypeName")) not in types:
                    return False
        return True

    def parseEnumeration(typeXml):	
        name = typeXml.get("Name")
        description = ""
        elements = OrderedDict()
        for child in typeXml:
            if child.tag == "{http://opcfoundation.org/BinarySchema/}Documentation":
                description = child.text
            if child.tag == "{http://opcfoundation.org/BinarySchema/}EnumeratedValue":
                elements[name + "_" + child.get("Name")] = child.get("Value")
        return EnumerationType(name, description, elements)

    def parseOpaque(typeXml):
        name = typeXml.get("Name")
        description = ""
        for child in typeXml:
            if child.tag == "{http://opcfoundation.org/BinarySchema/}Documentation":
                description = child.text
        return OpaqueType(name, description)

    def parseStructured(typeXml):
        "Returns None if we miss member descriptions"
        name = typeXml.get("Name")
        description = ""
        for child in typeXml:
            if child.tag == "{http://opcfoundation.org/BinarySchema/}Documentation":
                description = child.text
        # ignore lengthfields, just tag the array-members as an array
        lengthfields = []
        for child in typeXml:
            if child.get("LengthField"):
                lengthfields.append(child.get("LengthField"))
        members = OrderedDict()
        for child in typeXml:
            if not child.tag == "{http://opcfoundation.org/BinarySchema/}Field":
                continue
            if child.get("Name") in lengthfields:
                continue
            memberTypeName = stripTypename(child.get("TypeName"))
            if not memberTypeName in types:
                return None
            memberType = types[memberTypeName]
            memberName = child.get("Name")
            isArray = True if child.get("LengthField") else False
            members[memberName] = StructMember(memberName, memberType, isArray)
        return StructType(name, description, members)

    finished = False
    while(not finished):
        finished = True
        for typeXml in typeSnippets:
            name = typeXml.get("Name")
            if name in types or skipType(name):
                continue
            if typeXml.tag == "{http://opcfoundation.org/BinarySchema/}EnumeratedType":
                t = parseEnumeration(typeXml)
                types[t.name] = t
            elif typeXml.tag == "{http://opcfoundation.org/BinarySchema/}OpaqueType":
                t = parseOpaque(typeXml)
                types[t.name] = t
            elif typeXml.tag == "{http://opcfoundation.org/BinarySchema/}StructuredType":
                t = parseStructured(typeXml)
                if t == None:
                    finished = False
                else:
                    types[t.name] = t
    return types

parser = argparse.ArgumentParser()
parser.add_argument('types_xml', help='path/to/Opc.Ua.Types.bsd')
parser.add_argument('outfile', help='output file w/o extension')

args = parser.parse_args()
outname = args.outfile.split("/")[-1] 
inname = args.types_xml.split("/")[-1]
types = parseTypeDefinitions(args.types_xml)

idl = open(args.outfile + ".idl",'w')
def printidl(string):
    print(string, end='\n', file=idl)

printidl(''' module UA {

    // name clashes with IDL keywords are prevented by a "_" prefix

    typedef boolean _Boolean;
    union ListOfBoolean switch(boolean) { case true: sequence<_Boolean> Content; };

    typedef char SByte ;
    union ListOfSByte switch(boolean) { case true: sequence<SByte> Content; };

    typedef octet Byte;
    union ListOfByte switch(boolean) { case true: sequence<Byte> Content; };

    typedef short Int16;
    union ListOfInt16 switch(boolean) { case true: sequence<Int16> Content; };

    typedef unsigned short UInt16;
    union ListOfUInt16 switch(boolean) { case true: sequence<UInt16> Content; };

    typedef long Int32;
    union ListOfInt32 switch(boolean) { case true: sequence<Int32> Content; };

    typedef long StatusCode;
    union ListOfStatusCode switch(boolean) { case true: sequence<StatusCode> Content; };

    typedef unsigned long UInt32;
    union ListOfUInt32 switch(boolean) { case true: sequence<UInt32> Content; };

    typedef long long Int64;
    union ListOfInt64 switch(boolean) { case true: sequence<Int64> Content; };

    typedef float _Float;
    union ListOfFloat switch(boolean) { case true: sequence<_Float> Content; };

    typedef float _Double;
    union ListOfDouble switch(boolean) { case true: sequence<_Double> Content; };

    typedef long long DateTime;
    union ListOfDateTime switch(boolean) { case true: sequence<DateTime> Content; };

    typedef unsigned long long UInt64;
    union ListOfUInt64 switch(boolean) { case true: sequence<UInt64> Content; };

    typedef ListOfByte _String;
    union ListOfString switch(boolean) { case true: sequence<_String> Content; };

    typedef ListOfByte ByteString;
    union ListOfByteString switch(boolean) { case true: sequence<ByteString> Content; };

    typedef ListOfByte XmlElement;
    union ListOfXmlElement switch(boolean) { case true: sequence<XmlElement> Content; };

    struct Guid {
        UInt32 Data1;
        UInt32 Data2;
        UInt16 Data3;
        Byte Data4[8];
    };
    union ListOfGuid switch(boolean) { case true: sequence<Guid> Content; };
    
    enum NodeIdContent {
        NodeIdContentNumeric,
        NodeIdContentString,
        NodeIdContentGuid,
        NodeIdContentByteString
    };

    union NodeIdIdentifier switch(NodeIdContent) {
        case NodeIdContentNumeric: UInt32 Numeric;
        case NodeIdContentString: _String _String;
        case NodeIdContentGuid: Guid Guid;
        case NodeIdContentByteString: ByteString ByteString;
    };

    struct NodeId {
        unsigned short NamespaceIndex;
        NodeIdIdentifier Identifier;
    };
    union ListOfNodeId switch(boolean) { case true: sequence<NodeId> Content; };

    struct ExpandedNodeId {
        NodeId NodeId;
        _String NamespaceUri;
        UInt32 ServerIndex;
    };
    union ListOfExpandedNodeId switch(boolean) { case true: sequence<ExpandedNodeId> Content; };

    struct QualifiedName {
        UInt16 NamespaceIndex;
        _String Name;
    };
    union ListOfQualifiedName switch(boolean) { case true: sequence<QualifiedName> Content; };

    struct LocalizedText {
        _String Locale;
        _String Text;
    };
    union ListOfLocalizedText switch(boolean) { case true: sequence<LocalizedText> Content; };

    enum ExtensionObjectBodyType {
        ExtensionObjectBodyTypeNoBody,
        ExtensionObjectBodyTypeByteString,
        ExtensionObjectBodyTypeXml
    };

    union ExtensionObjectBody switch(ExtensionObjectBodyType) {
        case ExtensionObjectBodyTypeByteString: ByteString ByteString;
        case ExtensionObjectBodyTypeXml: XmlElement Xml;
    };
    
    struct ExtensionObject {
        NodeId _TypeId;
        ExtensionObjectBody Body;
    };
    union ListOfExtensionObject switch(boolean) { case true: sequence<ExtensionObject> Content; };

    struct Variant; // forward declaration
    union ListOfVariant switch(boolean) { case true: sequence<Variant> Content; };

    struct DataValue {
        sequence<Variant, 1> Value;
        sequence<StatusCode, 1> Status;
        sequence<DateTime, 1> SourceTimestamp;
        sequence<UInt16, 1> SourcePicoseconds;
        sequence<DateTime, 1> ServerTimestamp;
        sequence<UInt16, 1> ServerPicoseconds;
    };
    union ListOfDataValue switch(boolean) { case true: sequence<DataValue> Content; };

    struct DiagnosticInfo {
        sequence<Int32, 1> SymbolicId;
        sequence<Int32, 1> NamespaceUri;
        sequence<Int32, 1> LocalizedText;
        sequence<Int32, 1> Locale;
        sequence<_String, 1> AdditionalInfo;
        sequence<StatusCode, 1> InnerStatusCode;
        sequence<DiagnosticInfo, 1> InnerDiagnosticInfo;
    };
    union ListOfDiagnosticInfo switch(boolean) { case true: sequence<DiagnosticInfo> Content; };

    enum VariantContentType {
        VariantContentTypeBoolean,
        VariantContentTypeSByte,
        VariantContentTypeByte,
        VariantContentTypeInt16,
        VariantContentTypeUInt16,
        VariantContentTypeInt32,
        VariantContentTypeUInt32,
        VariantContentTypeFloat,
        VariantContentTypeDouble,
        VariantContentTypeString,
        VariantContentTypeDateTime,
        VariantContentTypeGuid,
        VariantContentTypeByteString,
        VariantContentTypeXmlElement,
        VariantContentTypeNodeId,
        VariantContentTypeExpandedNodeId,
        VariantContentTypeStatusCode,
        VariantContentTypeQualifiedName,
        VariantContentTypeLocalizedText,
        VariantContentTypeExtensionObject,
        VariantContentTypeDataValue,
        VariantContentTypeVariant,
        VariantContentTypeDiagnosticInfo
    };

    union VariantContent switch(VariantContentType) {
    case VariantContentTypeBoolean: ListOfBoolean _Boolean;
    case VariantContentTypeSByte: ListOfSByte SByte;
    case VariantContentTypeByte: ListOfByte Byte;
    case VariantContentTypeInt16: ListOfInt16 Int16;
    case VariantContentTypeUInt16: ListOfUInt16 UInt16;
    case VariantContentTypeInt32: ListOfInt32 Int32;
    case VariantContentTypeUInt32: ListOfUInt32 UInt32;
    case VariantContentTypeFloat: ListOfFloat _Float;
    case VariantContentTypeDouble: ListOfDouble _Double;
    case VariantContentTypeString: ListOfString _String;
    case VariantContentTypeDateTime: ListOfDateTime Datetime;
    case VariantContentTypeGuid: ListOfGuid Guid;
    case VariantContentTypeByteString: ListOfByteString ByteString;
    case VariantContentTypeXmlElement: ListOfXmlElement Xmlelement;
    case VariantContentTypeNodeId: ListOfNodeId NodeId;
    case VariantContentTypeExpandedNodeId: ListOfExpandedNodeId ExpandedNodeId;
    case VariantContentTypeStatusCode: ListOfStatusCode StatusCode;
    case VariantContentTypeQualifiedName: ListOfQualifiedName QualifiedName;
    case VariantContentTypeLocalizedText: ListOfLocalizedText LocalizedText;
    case VariantContentTypeExtensionObject: ListOfExtensionObject ExtensionObject;
    case VariantContentTypeDataValue: ListOfDataValue DataValue;
    case VariantContentTypeVariant: ListOfVariant Variant;
    case VariantContentTypeDiagnosticInfo: ListOfDiagnosticInfo DiagnosticInfo;
    };

    struct Variant {
        _Boolean scalar; // force the VariantContent to contain just one element
        VariantContent Content;
        ListOfUInt32 ArrayDimensions;
    };
''')

for name, t in types.iteritems():
    if name in builtin_types:
        continue
    printidl(t.typedef_idl())
    printidl("\tunion ListOf" + name + " switch(boolean) { case true: sequence<" + \
             name + "> Content; };\n")

printidl("};")
idl.close()

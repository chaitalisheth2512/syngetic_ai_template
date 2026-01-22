from typing import Annotated, Optional, TypedDict, List,  TypeVar, cast, Callable, Any
from enum import Enum

class FieldType(str, Enum):
    TEXT = "Text"
    SINGLE_LINE = "SingleLine"
    NUMBER = "Number"
    BOOLEAN = "Boolean"
    SINGLE_SELECT = "SingleSelect"
    MULTI_SELECT = "MultiSelect"

class FieldRequired(TypedDict):
    id:str
    label:str
    type:FieldType
    
class Field(FieldRequired, total=False):
    options:List[str]
    width:str

class Pin(TypedDict):
    name:str

class PinCollection(TypedDict):
    trigger_pins:List[Pin]
    input_pins:List[Pin]
    output_pins:List[Pin]
    next_pins:List[Pin]
 
class NodeConfig(TypedDict):
    id:str
    description:str | None
    name:str
    pins:PinCollection
    fields:List[Field]  

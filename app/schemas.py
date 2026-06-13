from typing import Annotated, Optional
from annotated_types import Ge, Le
from pydantic import BaseModel, StringConstraints, ConfigDict

# ---------- Reusable type aliases ----------
IDModuleInt = Annotated[int, Ge(1000), Le(9999)]
NameStr = Annotated[str, StringConstraints(min_length=1, max_length=100)]

# ---------- Module ----------
class ModuleCreate(BaseModel):
    id_module: IDModuleInt
    name: NameStr
    course_id: int  # Required - modules must belong to a course

class ModuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_module: IDModuleInt
    name: NameStr
    course_id: int
    enrolled_users: list[str] = []

#Partial update module
class ModuleUpdate(BaseModel):
    id_module: Optional[IDModuleInt] = None
    name: Optional[NameStr] = None
    course_id: Optional[int] = None

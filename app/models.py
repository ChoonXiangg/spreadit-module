from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

# Independent table
class ModuleDB(Base):
    __tablename__ = "module"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_module: Mapped[int] = mapped_column(unique=True, nullable=False) # required field
    name: Mapped[str] = mapped_column(nullable=False) # required field
    course_id: Mapped[str] = mapped_column(nullable=True) # Optional link to course
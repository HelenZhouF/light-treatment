from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.database import Base


class TreatmentDefinition(Base):
    __tablename__ = "treatment_definitions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    createdBy = Column(String(255), nullable=True)
    creationTimeStamp = Column(DateTime, default=datetime.utcnow)
    modifiedBy = Column(String(255), nullable=True)
    modifiedTimeStamp = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    majorRevision = Column(Integer, default=1)
    minorRevision = Column(Integer, default=0)
    checkout = Column(Boolean, default=False)
    locked = Column(Boolean, default=False)
    status = Column(String(50), default="valid")
    folderType = Column(String(255), nullable=True)
    sourceRevisionUri = Column(Text, nullable=True)
    copyTimeStamp = Column(DateTime, nullable=True)

    version = Column(Integer, default=1)

    attributes = relationship("Attribute", back_populates="treatment_definition", cascade="all, delete-orphan")


class Attribute(Base):
    __tablename__ = "attributes"

    id = Column(Integer, primary_key=True, index=True)
    treatment_definition_id = Column(Integer, ForeignKey("treatment_definitions.id"), nullable=False)
    name = Column(String(255), nullable=False)
    defaultValue = Column(Text, nullable=True)

    valueConstraints = relationship("ValueConstraint", back_populates="attribute", cascade="all, delete-orphan", uselist=False)
    treatment_definition = relationship("TreatmentDefinition", back_populates="attributes")


class ValueConstraint(Base):
    __tablename__ = "value_constraints"

    id = Column(Integer, primary_key=True, index=True)
    attribute_id = Column(Integer, ForeignKey("attributes.id"), nullable=False)

    dataType = Column(String(50), nullable=False)
    format = Column(String(50), nullable=True)

    required = Column(Boolean, default=False)
    readOnly = Column(Boolean, default=False)
    multiple = Column(Boolean, default=False)
    range = Column(Boolean, default=False)

    enumValues = Column(Text, nullable=True)

    attribute = relationship("Attribute", back_populates="valueConstraints")

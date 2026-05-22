from fastapi import FastAPI, Response, Request, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_, or_
from sqlalchemy.orm import selectinload
from typing import Optional
import json
import traceback
import re

from app.database import init_db, async_session
from app.models import TreatmentDefinition, Attribute, ValueConstraint
from app.schemas import (
    TreatmentDefinitionRoot,
    TreatmentDefinitionCreate,
    TreatmentDefinitionUpdate,
    Link,
)

app = FastAPI(
    title="Light Treatment API",
    description="API for light treatment definitions",
    version="1.0.0",
)


@app.on_event("startup")
async def startup_event():
    await init_db()


MEDIA_TYPE_DEFINITION = "application/vnd.sas.treatment.definition+json"
MEDIA_TYPE_COLLECTION = "application/vnd.sas.collection+json"
MEDIA_TYPE_SUMMARY = "application/vnd.sas.summary+json"
MEDIA_TYPE_ROOT = "application/vnd.sas.api"


BASE_URI = "/treatmentDefinition/definitions"


class FilterParseError(Exception):
    """Exception raised for invalid filter syntax"""
    pass


def parse_filter(filter_str: str):
    """Parse filter expression like eq(name,'Test') or gt(id,5) or in(name,'val1','val2')"""
    
    valid_operators = ['eq', 'gt', 'lt', 'ge', 'le', 'ne', 'contains', 'startsWith', 'in']
    
    value_pattern = r"(?:'([^']*)'|(\d+(?:\.\d+)?))"
    
    patterns = {
        'eq': rf"eq\((\w+),\s*{value_pattern}\)",
        'gt': rf"gt\((\w+),\s*{value_pattern}\)",
        'lt': rf"lt\((\w+),\s*{value_pattern}\)",
        'ge': rf"ge\((\w+),\s*{value_pattern}\)",
        'le': rf"le\((\w+),\s*{value_pattern}\)",
        'ne': rf"ne\((\w+),\s*{value_pattern}\)",
        'contains': rf"contains\((\w+),\s*{value_pattern}\)",
        'startsWith': rf"startsWith\((\w+),\s*{value_pattern}\)",
        'in': r"in\((\w+),\s*((?:'[^']*')(?:\s*,\s*'[^']*')*)\)",
    }
    
    filters = []
    
    found_any = False
    for op, pattern in patterns.items():
        matches = re.findall(pattern, filter_str)
        for match in matches:
            found_any = True
            field_name = match[0]
            
            if op == 'in':
                values_str = match[1]
                values = re.findall(r"'([^']*)'", values_str)
                filters.append({
                    'operator': op,
                    'field': field_name,
                    'values': values
                })
            else:
                str_value = match[1]
                num_value = match[2]
                
                if num_value and num_value != '':
                    value = float(num_value) if '.' in num_value else int(num_value)
                else:
                    value = str_value
                
                filters.append({
                    'operator': op,
                    'field': field_name,
                    'value': value
                })
    
    if not found_any and filter_str:
        valid_ops_pattern = '|'.join(valid_operators)
        if not re.match(rf"^\s*({valid_ops_pattern})\s*\(", filter_str):
            raise FilterParseError(f"Invalid filter syntax: '{filter_str}'. Valid operators are: {', '.join(valid_operators)}")
        
        if not re.match(rf"^\s*({valid_ops_pattern})\s*\(\s*\w+\s*,", filter_str):
            raise FilterParseError(f"Invalid filter syntax: '{filter_str}'. Expected field name after operator")
    
    return filters


def apply_filters(query, filters, model):
    """Apply parsed filters to SQLAlchemy query"""
    conditions = []
    for f in filters:
        field_name = f['field']
        operator = f['operator']
        
        if not hasattr(model, field_name):
            continue
        
        column = getattr(model, field_name)
        
        if operator == 'in':
            values = f.get('values', [])
            if values:
                conditions.append(column.in_(values))
        else:
            value = f['value']
            
            if operator == 'eq':
                conditions.append(column == value)
            elif operator == 'gt':
                conditions.append(column > value)
            elif operator == 'lt':
                conditions.append(column < value)
            elif operator == 'ge':
                conditions.append(column >= value)
            elif operator == 'le':
                conditions.append(column <= value)
            elif operator == 'ne':
                conditions.append(column != value)
            elif operator == 'contains':
                conditions.append(column.contains(str(value)))
            elif operator == 'startsWith':
                conditions.append(column.startswith(str(value)))
    
    if conditions:
        query = query.where(and_(*conditions))
    
    return query


def parse_sort_by(sort_by_str: str):
    """Parse sortBy parameter like 'name:ascending' or 'modifiedTimeStamp:descending'"""
    parts = sort_by_str.split(':')
    if len(parts) != 2:
        return None, None
    
    field_name, direction = parts
    direction = direction.lower()
    
    if direction not in ('ascending', 'descending'):
        return None, None
    
    return field_name, direction


def link_to_dict(link: Link) -> dict:
    return link.model_dump()


def generate_definition_links(definition_id: int) -> list[dict]:
    return [
        link_to_dict(Link(rel="self", href=f"{BASE_URI}/{definition_id}", method="GET", type=MEDIA_TYPE_DEFINITION)),
        link_to_dict(Link(rel="up", href=f"{BASE_URI}", method="GET", type=MEDIA_TYPE_COLLECTION)),
        link_to_dict(Link(rel="alternate", href=f"{BASE_URI}/{definition_id}?view=summary", method="GET", type=MEDIA_TYPE_SUMMARY)),
        link_to_dict(Link(rel="update", href=f"{BASE_URI}/{definition_id}", method="PUT", type=MEDIA_TYPE_DEFINITION)),
        link_to_dict(Link(rel="delete", href=f"{BASE_URI}/{definition_id}", method="DELETE")),
        link_to_dict(Link(rel="revisions", href=f"{BASE_URI}/{definition_id}?view=revisionSummary", method="GET", type=MEDIA_TYPE_SUMMARY)),
        link_to_dict(Link(rel="dependencies", href=f"{BASE_URI}/{definition_id}/dependencies", method="GET")),
    ]


def generate_collection_links(start: int, limit: int, count: int) -> list[dict]:
    links = [
        link_to_dict(Link(rel="self", href=f"{BASE_URI}?start={start}&limit={limit}", method="GET", type=MEDIA_TYPE_COLLECTION)),
        link_to_dict(Link(rel="create", href=f"{BASE_URI}", method="POST", type=MEDIA_TYPE_DEFINITION)),
    ]
    if start + limit < count:
        links.append(
            link_to_dict(Link(
                rel="next",
                href=f"{BASE_URI}?start={start + limit}&limit={limit}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ))
        )
    if start > 0:
        prev_start = max(0, start - limit)
        links.append(
            link_to_dict(Link(
                rel="prev",
                href=f"{BASE_URI}?start={prev_start}&limit={limit}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ))
        )
    return links


def model_to_response(model: TreatmentDefinition) -> dict:
    data = {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "createdBy": model.createdBy,
        "creationTimeStamp": model.creationTimeStamp.isoformat() if model.creationTimeStamp else None,
        "modifiedBy": model.modifiedBy,
        "modifiedTimeStamp": model.modifiedTimeStamp.isoformat() if model.modifiedTimeStamp else None,
        "majorRevision": model.majorRevision,
        "minorRevision": model.minorRevision,
        "checkout": model.checkout,
        "locked": model.locked,
        "status": model.status,
        "folderType": model.folderType,
        "sourceRevisionUri": model.sourceRevisionUri,
        "copyTimeStamp": model.copyTimeStamp.isoformat() if model.copyTimeStamp else None,
        "version": model.version,
        "attributes": [],
        "links": generate_definition_links(model.id),
    }
    for attr in model.attributes:
        attr_data = {
            "id": attr.id,
            "name": attr.name,
            "defaultValue": attr.defaultValue,
        }
        if attr.valueConstraints:
            vc = attr.valueConstraints
            attr_data["valueConstraints"] = {
                "id": vc.id,
                "dataType": vc.dataType,
                "format": vc.format,
                "required": vc.required,
                "readOnly": vc.readOnly,
                "multiple": vc.multiple,
                "range": vc.range,
                "enum": json.loads(vc.enumValues) if vc.enumValues else None,
            }
        data["attributes"].append(attr_data)
    return data


def model_to_summary(model: TreatmentDefinition) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "createdBy": model.createdBy,
        "creationTimeStamp": model.creationTimeStamp.isoformat() if model.creationTimeStamp else None,
        "modifiedBy": model.modifiedBy,
        "modifiedTimeStamp": model.modifiedTimeStamp.isoformat() if model.modifiedTimeStamp else None,
        "majorRevision": model.majorRevision,
        "minorRevision": model.minorRevision,
        "checkout": model.checkout,
        "locked": model.locked,
        "status": model.status,
        "links": generate_definition_links(model.id),
    }


def model_to_revision_summary(model: TreatmentDefinition) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "majorRevision": model.majorRevision,
        "minorRevision": model.minorRevision,
        "status": model.status,
        "links": generate_definition_links(model.id),
    }


async def create_attributes_from_schema(db: AsyncSession, treatment_def_id: int, attributes: list):
    for attr_data in attributes:
        attr = Attribute(
            treatment_definition_id=treatment_def_id,
            name=attr_data.name,
            defaultValue=attr_data.defaultValue,
        )
        db.add(attr)
        await db.flush()

        if attr_data.valueConstraints:
            vc = attr_data.valueConstraints
            vc_obj = ValueConstraint(
                attribute_id=attr.id,
                dataType=vc.dataType,
                format=vc.format,
                required=vc.required or False,
                readOnly=vc.readOnly or False,
                multiple=vc.multiple or False,
                range=vc.range or False,
                enumValues=json.dumps(vc.enum) if vc.enum else None,
            )
            db.add(vc_obj)


@app.get(
    "/treatmentDefinition",
    response_model=TreatmentDefinitionRoot,
    responses={
        200: {
            "content": {MEDIA_TYPE_ROOT: {}},
            "description": "Root entry point for treatment definitions service",
        }
    },
)
async def get_treatment_definition_root():
    root = TreatmentDefinitionRoot(
        links=[
            Link(
                rel="treatmentDefinitions",
                href=f"{BASE_URI}",
                method="GET",
                type=MEDIA_TYPE_COLLECTION,
            ),
            Link(
                rel="createTreatmentDefinition",
                href=f"{BASE_URI}",
                method="POST",
                type=MEDIA_TYPE_DEFINITION,
            ),
        ]
    )
    return JSONResponse(
        content=root.model_dump(),
        media_type=MEDIA_TYPE_ROOT,
    )


@app.get(
    f"{BASE_URI}",
    responses={
        200: {
            "content": {
                MEDIA_TYPE_COLLECTION: {},
                MEDIA_TYPE_SUMMARY: {},
            },
            "description": "Collection of treatment definitions",
        }
    },
)
async def get_definitions(
    request: Request,
    start: int = Query(0, ge=0, description="Start index for pagination"),
    limit: int = Query(10, ge=1, le=100, description="Maximum items to return"),
    filter: Optional[str] = Query(None, description="Filter criteria (e.g., eq(name,'Test'))"),
    sortBy: Optional[str] = Query(None, description="Sort by field (e.g., name:ascending)"),
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    try:
        parsed_filters = parse_filter(filter) if filter else []
    except FilterParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    async with async_session() as db:
        query = select(TreatmentDefinition).options(
            selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
        )

        if filter:
            query = apply_filters(query, parsed_filters, TreatmentDefinition)

        if sortBy:
            sort_field, direction = parse_sort_by(sortBy)
            if sort_field and hasattr(TreatmentDefinition, sort_field):
                column = getattr(TreatmentDefinition, sort_field)
                if direction == 'descending':
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column)
            else:
                query = query.order_by(TreatmentDefinition.id)
        else:
            query = query.order_by(TreatmentDefinition.id)

        count_query = select(func.count()).select_from(TreatmentDefinition)
        if filter:
            count_query = apply_filters(count_query, parsed_filters, TreatmentDefinition)
        result = await db.execute(count_query)
        count = result.scalar()

        query = query.offset(start).limit(limit)
        result = await db.execute(query)
        definitions = result.scalars().all()

        use_summary = accept_item == MEDIA_TYPE_SUMMARY

        if use_summary:
            items = [model_to_summary(d) for d in definitions]
            media_type = MEDIA_TYPE_SUMMARY
        else:
            items = [model_to_response(d) for d in definitions]
            media_type = MEDIA_TYPE_COLLECTION

        collection = {
            "items": items,
            "start": start,
            "limit": limit,
            "count": count,
            "links": generate_collection_links(start, limit, count),
        }

        return JSONResponse(content=collection, media_type=media_type)


@app.get(
    f"{BASE_URI}/{{definition_id}}",
    responses={
        200: {
            "content": {
                MEDIA_TYPE_DEFINITION: {},
                MEDIA_TYPE_SUMMARY: {},
            },
            "description": "Treatment definition",
        },
        404: {"description": "Definition not found"},
    },
)
async def get_definition(
    definition_id: int,
    request: Request,
    view: Optional[str] = Query(None, description="View type: summary or revisionSummary"),
    accept_item: Optional[str] = Header(None, alias="Accept-Item"),
):
    async with async_session() as db:
        query = select(TreatmentDefinition).options(
            selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
        ).where(TreatmentDefinition.id == definition_id)
        result = await db.execute(query)
        definition = result.scalar_one_or_none()

        if not definition:
            raise HTTPException(status_code=404, detail="Definition not found")

        url_fragment = request.url.fragment if request.url.fragment else None
        
        is_summary = (view == "summary") or (url_fragment == "summary")
        is_revision = (view == "revisionSummary") or (url_fragment == "revisionSummary")

        if is_revision or accept_item == "application/vnd.sas.revision.summary+json":
            data = model_to_revision_summary(definition)
            media_type = MEDIA_TYPE_SUMMARY
        elif is_summary or accept_item == MEDIA_TYPE_SUMMARY:
            data = model_to_summary(definition)
            media_type = MEDIA_TYPE_SUMMARY
        else:
            data = model_to_response(definition)
            media_type = MEDIA_TYPE_DEFINITION

        return JSONResponse(content=data, media_type=media_type)


@app.post(
    f"{BASE_URI}",
    status_code=201,
    responses={
        201: {
            "content": {MEDIA_TYPE_DEFINITION: {}},
            "description": "Created treatment definition",
        },
        400: {"description": "Invalid input"},
    },
)
async def create_definition(
    definition: TreatmentDefinitionCreate,
    request: Request,
):
    try:
        async with async_session() as db:
            new_def = TreatmentDefinition(
                name=definition.name,
                description=definition.description,
                createdBy="system",
                modifiedBy="system",
            )
            db.add(new_def)
            await db.flush()

            if definition.attributes:
                await create_attributes_from_schema(db, new_def.id, definition.attributes)

            await db.commit()
            def_id = new_def.id
            def_version = new_def.version

        async with async_session() as db:
            query = select(TreatmentDefinition).options(
                selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
            ).where(TreatmentDefinition.id == def_id)
            result = await db.execute(query)
            created_def = result.scalar_one()

            data = model_to_response(created_def)
            response = JSONResponse(
                content=data,
                status_code=201,
                media_type=MEDIA_TYPE_DEFINITION,
            )
            response.headers["Location"] = f"{BASE_URI}/{created_def.id}"
            response.headers["ETag"] = str(def_version)
            return response
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.put(
    f"{BASE_URI}/{{definition_id}}",
    responses={
        200: {
            "content": {MEDIA_TYPE_DEFINITION: {}},
            "description": "Updated treatment definition",
        },
        400: {"description": "Invalid input"},
        404: {"description": "Definition not found"},
        412: {"description": "Precondition failed (ETag mismatch)"},
    },
)
async def update_definition(
    definition_id: int,
    definition: TreatmentDefinitionUpdate,
    request: Request,
    if_match: Optional[str] = Header(None, alias="If-Match"),
):
    try:
        async with async_session() as db:
            query = select(TreatmentDefinition).options(
                selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
            ).where(TreatmentDefinition.id == definition_id)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if not existing:
                raise HTTPException(status_code=404, detail="Definition not found")

            if if_match and str(existing.version) != if_match:
                raise HTTPException(status_code=412, detail="ETag mismatch")

            if definition.name is not None:
                existing.name = definition.name
            if definition.description is not None:
                existing.description = definition.description

            existing.modifiedBy = "system"
            existing.version = existing.version + 1
            existing.minorRevision = existing.minorRevision + 1

            if definition.attributes is not None:
                await db.execute(delete(ValueConstraint).where(
                    ValueConstraint.attribute_id.in_(
                        select(Attribute.id).where(Attribute.treatment_definition_id == definition_id)
                    )
                ))
                await db.execute(delete(Attribute).where(Attribute.treatment_definition_id == definition_id))

                await create_attributes_from_schema(db, definition_id, definition.attributes)

            await db.commit()
            def_version = existing.version

        async with async_session() as db:
            query = select(TreatmentDefinition).options(
                selectinload(TreatmentDefinition.attributes).selectinload(Attribute.valueConstraints)
            ).where(TreatmentDefinition.id == definition_id)
            result = await db.execute(query)
            updated_def = result.scalar_one()

            data = model_to_response(updated_def)
            response = JSONResponse(
                content=data,
                status_code=200,
                media_type=MEDIA_TYPE_DEFINITION,
            )
            response.headers["ETag"] = str(def_version)
            return response
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.delete(
    f"{BASE_URI}/{{definition_id}}",
    status_code=204,
    responses={
        204: {"description": "Definition deleted successfully"},
        404: {"description": "Definition not found"},
    },
)
async def delete_definition(
    definition_id: int,
    request: Request,
):
    try:
        async with async_session() as db:
            query = select(TreatmentDefinition).where(TreatmentDefinition.id == definition_id)
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if not existing:
                raise HTTPException(status_code=404, detail="Definition not found")

            await db.execute(delete(ValueConstraint).where(
                ValueConstraint.attribute_id.in_(
                    select(Attribute.id).where(Attribute.treatment_definition_id == definition_id)
                )
            ))
            await db.execute(delete(Attribute).where(Attribute.treatment_definition_id == definition_id))
            await db.delete(existing)
            await db.commit()

            return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    f"{BASE_URI}/{{definition_id}}/dependencies",
    responses={
        200: {
            "content": {MEDIA_TYPE_COLLECTION: {}},
            "description": "Direct dependencies of the definition",
        },
        404: {"description": "Definition not found"},
    },
)
async def get_definition_dependencies(
    definition_id: int,
    request: Request,
):
    async with async_session() as db:
        query = select(TreatmentDefinition).where(TreatmentDefinition.id == definition_id)
        result = await db.execute(query)
        definition = result.scalar_one_or_none()

        if not definition:
            raise HTTPException(status_code=404, detail="Definition not found")

        collection = {
            "items": [],
            "start": 0,
            "limit": 0,
            "count": 0,
            "links": [
                link_to_dict(Link(rel="self", href=f"{BASE_URI}/{definition_id}/dependencies", method="GET", type=MEDIA_TYPE_COLLECTION)),
                link_to_dict(Link(rel="up", href=f"{BASE_URI}/{definition_id}", method="GET", type=MEDIA_TYPE_DEFINITION)),
            ],
        }

        return JSONResponse(content=collection, media_type=MEDIA_TYPE_COLLECTION)

"""Wire-schema bounds matching the shared service's existing input checks."""

from typing import Annotated

from pydantic import Field

Offset = Annotated[int, Field(ge=0, strict=True)]
Limit = Annotated[int, Field(ge=1, le=200, strict=True)]
IndexLimit = Annotated[int, Field(ge=1, le=5, strict=True)]
Page = Annotated[int, Field(ge=1, strict=True)]
Width = Annotated[int, Field(ge=1, le=3000, strict=True)]
TextLength = Annotated[int, Field(ge=1, le=16000, strict=True)]
ArtifactLength = Annotated[int, Field(ge=1, le=65536, strict=True)]
TraceDepth = Annotated[int, Field(ge=1, le=100, strict=True)]
TracePaths = Annotated[int, Field(ge=1, le=200, strict=True)]
Tolerance = Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]

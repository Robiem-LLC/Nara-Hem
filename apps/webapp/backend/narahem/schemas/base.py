"""The strict base models every request body derives from."""

from pydantic import BaseModel, ConfigDict

MAX_DEVICES = 32


class Input(BaseModel):
    """Base class for request bodies. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class CryptoInput(Input):
    """Base class for signed bodies. Strict mode prevents type coercion before signature checks."""

    model_config = ConfigDict(extra="forbid", strict=True)

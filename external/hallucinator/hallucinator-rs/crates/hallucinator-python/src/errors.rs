use pyo3::PyErr;
use pyo3::exceptions::PyRuntimeError;

use hallucinator_core::BackendError;
use hallucinator_parsing::ParsingError;

/// Convert a `ParsingError` into a Python exception.
pub fn parsing_error_to_py(e: ParsingError) -> PyErr {
    PyRuntimeError::new_err(e.to_string())
}

/// Convert a `BackendError` into a Python exception.
pub fn backend_error_to_py(e: BackendError) -> PyErr {
    PyRuntimeError::new_err(e.to_string())
}

use std::path::Path;

use thiserror::Error;

#[derive(Error, Debug)]
pub enum BackendError {
    #[error("failed to open PDF: {0}")]
    OpenError(String),
    #[error("failed to extract text: {0}")]
    ExtractionError(String),
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

/// Trait for PDF text extraction backends.
///
/// Implementors provide the low-level text extraction step; the parsing
/// pipeline (section detection, reference segmentation, title/author extraction)
/// lives in [`hallucinator_parsing::ReferenceExtractor`].
pub trait PdfBackend: Send + Sync {
    /// Extract the full text content of a PDF file.
    fn extract_text(&self, path: &Path) -> Result<String, BackendError>;
}

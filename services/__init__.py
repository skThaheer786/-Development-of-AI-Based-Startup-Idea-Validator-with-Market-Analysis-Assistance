# Services package initialization
from .groq_service import GroqService, LLMError
from .search_service import SearchService

__all__ = ["GroqService", "LLMError", "SearchService", "PDFReportService"]


def __getattr__(name):
    # PDF service is imported lazily (it pulls in reportlab)
    if name == "PDFReportService":
        from .pdf_service import PDFReportService
        return PDFReportService
    raise AttributeError(name)

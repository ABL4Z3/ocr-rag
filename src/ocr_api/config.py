from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    project_name: str = "OCR API"
    version: str = "0.1.0"
    ocr_lang: str = "en"
    ocr_dpi: int = 220
    ocr_eager_load: bool = False
    ocr_use_doc_orientation_classify: bool = False
    ocr_use_doc_unwarping: bool = False
    ocr_use_textline_orientation: bool = False


settings = Settings()


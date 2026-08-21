from django.tasks import task
import logging

logger = logging.getLogger(__name__)

@task()
def process_source(source_id: str):
    """
    Stub for the source processing task.
    Will eventually handle file parsing, transcription, etc.
    """
    from .models import BrandSource
    try:
        source = BrandSource.objects.get(id=source_id)
        logger.info(f"Processing source {source.id}")
        
        # In PR6, actual processing logic goes here
        # For now, just mark it PROCESSING (not READY) as it is a stub
        source.status = BrandSource.SourceStatus.PROCESSING
        source.save()
        
        # Enqueue memory extraction (stub)
        extract_memories.enqueue(str(source.id))
        
        return {"status": "success", "message": "Source processed"}
    except BrandSource.DoesNotExist:
        logger.error(f"Source {source_id} not found")
        return {"status": "error", "message": "Source not found"}
    except Exception as e:
        logger.exception(f"Error processing source {source_id}")
        source = BrandSource.objects.get(id=source_id)
        source.status = BrandSource.SourceStatus.FAILED
        source.save()
        raise e

@task()
def extract_memories(source_id: str):
    """
    Stub for extracting memories from a processed source.
    """
    from .models import BrandSource
    try:
        source = BrandSource.objects.get(id=source_id)
        logger.info(f"Extracting memories for source {source.id}")
        
        # In PR6, actual AI extraction logic goes here
        
        return {"status": "success", "message": "Memories extracted"}
    except BrandSource.DoesNotExist:
        return {"status": "error", "message": "Source not found"}

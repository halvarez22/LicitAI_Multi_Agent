import json
import redis
import sys
import os

sys.path.append(os.getcwd())

from app.config.settings import settings

redis_client = redis.Redis(
    host=settings.REDIS_HOST, 
    port=settings.REDIS_PORT, 
    decode_responses=True
)

job_id = "a7661b37-2ad4-4360-bfad-ec32ec8ad503"
job_data = redis_client.get(f"job:{job_id}")
if job_data:
    job = json.loads(job_data)
    print(f"Session ID: {job.get('result', {}).get('session_id')}")
    print(f"Status: {job.get('status')}")
    result = job.get("result", {})
    print(f"Result keys: {list(result.keys())}")
    fast_track = result.get("fast_track_document_candidates", {})
    print(json.dumps(fast_track, indent=2))
else:
    print("Job not found")

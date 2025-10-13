# app/memory_storage.py

bulk_profile_tasks_storage = {
    "tasks": []
}

like_loops_runtime = {
    # task_id: {"event": asyncio.Event, "task": asyncio.Task}
}
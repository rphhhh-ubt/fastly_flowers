# task_cards.py

TASK_CARD_DEFINITIONS = {
    "bulk_profile_update": {
        "fields": ["task_id", "account_count", "start_date", "end_date", "status"],
        "buttons": ["show_logs", "repeat_task", "delete_task", "back"]
    },
    "delete_channels": {
        "fields": ["task_id", "account_count", "start_date", "end_date", "status"],
        "buttons": ["show_logs", "repeat_task", "delete_task", "back"]
    }
    # в будущем легко добавлять другие типы задач:
    # "another_task_type": {
    #     "fields": ["field1", "field2", "field3"],
    #     "buttons": ["btn1", "btn2"]
    # }
}

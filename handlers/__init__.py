# handlers/__init__.py

from aiogram import Dispatcher
from . import start, accounts
from handlers.proxies import router as proxies_router
from handlers import bulk_profile_update_task, tasks_view
from .delete_old_channels import router as delete_old_channels_router
from .channel_creation import router as channel_creation_router
from . import delete_channels_selected, create_channel_selected, tasks_view
from .check_group_open import router as check_group_open_router
from .check_groups_task import router as check_groups_task_router
from .check_groups_card import router as check_groups_card_router
from .api_keys import router as api_keys_router
from .account_groups import router as account_groups_router
from .search_groups import router as search_groups_router
from .mass_search import router as mass_search_router
from .mass_search_view import router as mass_search_view_router
from .join_groups_task import router as join_groups_task_router
from .testsend import router as testsend_router
from .like_comments_task import router as like_comments_router
from .twofa import router as twofa_router
from .reauthorize_accounts import router as reauthorize_accounts_router
from .comment_check import router as comment_check_router
from .boost_views import router as boost_views_router
    



def register_all_handlers(dp: Dispatcher):
    dp.include_router(start.router)
    dp.include_router(accounts.router)
    dp.include_router(proxies_router)
    dp.include_router(bulk_profile_update_task.router)    
    dp.include_router(delete_old_channels_router)
    dp.include_router(channel_creation_router)
    dp.include_router(delete_channels_selected.router)
    dp.include_router(tasks_view.router)
    dp.include_router(create_channel_selected.router)
    dp.include_router(check_group_open_router)
    dp.include_router(check_groups_task_router)
    dp.include_router(check_groups_card_router)
    dp.include_router(api_keys_router)
    dp.include_router(account_groups_router)
    dp.include_router(search_groups_router)
    dp.include_router(mass_search_router)
    dp.include_router(mass_search_view_router)
    dp.include_router(join_groups_task_router)
    dp.include_router(testsend_router)
    dp.include_router(like_comments_router)
    dp.include_router(twofa_router)
    dp.include_router(reauthorize_accounts_router)
    dp.include_router(comment_check_router)
    dp.include_router(boost_views_router)
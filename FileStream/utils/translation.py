from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from FileStream.config import Telegram

class LANG(object):

    START_TEXT = """
**👋 ආයුබෝවන්, {}!**\n
**POP Tv One ලින්ක් ජෙනරේටර් වෙත ඔබව සාදරයෙන් පිළිගනිමු.**\n
**මට චිත්‍රපටයක හෝ කතා මාලාවක file එකක් එවන්න. මම ඔබට Download සහ Stream කරන්න පුළුවන් link එකක් ක්ෂණිකව සාදා දෙන්නම්.**\n
**🇱🇰 @{}**
"""

    HELP_TEXT = """
**භාවිතා කරන ආකාරය:**\n
**1. මාව ඔබේ Channel එකට Admin කෙනෙක් විදිහට Add කරන්න.**
**2. ඔබට Link එකක් අවශ්‍ය ඕනෑම file එකක් මට එවන්න.**
**3. මම ඔබට Stream සහ Download කරන්න පුළුවන් link එකක් සාදා දෙන්නම්.**\n
**වැඩි විස්තර සහ අලුත්ම චිත්‍රපට සඳහා අපගේ නිල චැනලය වෙත පිවිසෙන්න: @POPTvOne**
"""

    ABOUT_TEXT = """
**⚜️ නම : {}**\n
**✦ සංස්කරණය : {}**
**✦ නිර්මාණය : POP Tv One™**
**✦ Developer : @Mr_D_2000**
"""

    STREAM_TEXT = """
**ඔබගේ ලින්ක් එක සූදානම්!**\n
**📂 ගොනුවේ නම :** **{}**\n
**📦 ගොනුවේ ප්‍රමාණය :** <code>{}</code>\n
**📥 බාගත කිරීමට (Download) :** <code>{}</code>\n
**🖥 නැරඹීමට (Watch) :** <code>{}</code>\n
**🔗 මිතුරන් සමග බෙදාගන්න (Share) :** <code>{}</code>\n
"""

    STREAM_TEXT_X = """
**ඔබගේ ලින්ක් එක සූදානම්!**\n
**📂 ගොනුවේ නම :** **{}**\n
**📦 ගොනුවේ ප්‍රමාණය :** <code>{}</code>\n
**📥 බාගත කිරීමට (Download) :** <code>{}</code>\n
**🔗 මිතුරන් සමග බෙදාගන්න (Share) :** <code>{}</code>\n
"""


    BAN_TEXT = "**කණගාටුයි, ඔබව මෙම සේවාවෙන් තහනම් කර ඇත.**\n\n**වැඩි විස්තර සඳහා [පරිපාලක](tg://user?id={}) අමතන්න.**"


class BUTTON(object):
    START_BUTTONS = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton('සහාය (Help)', callback_data='help'),
            InlineKeyboardButton('ගැන (About)', callback_data='about'),
            InlineKeyboardButton('වසන්න (Close)', callback_data='close')
        ],
            [InlineKeyboardButton("📢 අපේ චැනලය (POP Tv One)", url='https://t.me/POPTvOne')]
        ]
    )
    HELP_BUTTONS = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton('මුල් පිටුව (Home)', callback_data='home'),
            InlineKeyboardButton('ගැන (About)', callback_data='about'),
            InlineKeyboardButton('වසන්න (Close)', callback_data='close'),
        ],
            [InlineKeyboardButton("📢 අපේ චැනලය (POP Tv One)", url='https://t.me/POPTvOne')]
        ]
    )
    ABOUT_BUTTONS = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton('මුල් පිටුව (Home)', callback_data='home'),
            InlineKeyboardButton('සහාය (Help)', callback_data='help'),
            InlineKeyboardButton('වසන්න (Close)', callback_data='close'),
        ],
            [InlineKeyboardButton("📢 අපේ චැනලය (POP Tv One)", url='https://t.me/POPTvOne')]
        ]
    )

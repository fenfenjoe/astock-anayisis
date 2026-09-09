{
  "behaviors": [
    {"id": "reading",    "label": "📖 阅读",  "weight": 15, "duration_min": 30, "duration_max": 60,  "require_llm": true},
    {"id": "gaming",     "label": "🎮 打游戏", "weight": 12, "duration_min": 30, "duration_max": 90,  "require_llm": false},
    {"id": "drama",      "label": "🎬 煲剧",   "weight": 10, "duration_min": 30, "duration_max": 60,  "require_llm": false},
    {"id": "shopping",   "label": "🛍️ 逛淘宝", "weight": 8,  "duration_min": 15, "duration_max": 45,  "require_llm": false},
    {"id": "music",      "label": "🎧 听歌",   "weight": 8,  "duration_min": 10, "duration_max": 30,  "require_llm": false},
    {"id": "cooking",    "label": "🍳 煮泡面", "weight": 6,  "duration_min": 10, "duration_max": 25,  "require_llm": false},
    {"id": "cat",        "label": "🐱 撸猫",   "weight": 7,  "duration_min": 15, "duration_max": 45,  "require_llm": false},
    {"id": "yoga",       "label": "🧘 做瑜伽", "weight": 5,  "duration_min": 15, "duration_max": 30,  "require_llm": false},
    {"id": "tea",        "label": "☕ 喝奶茶", "weight": 8,  "duration_min": 10, "duration_max": 25,  "require_llm": false},
    {"id": "drawing",    "label": "🎨 画画",   "weight": 5,  "duration_min": 30, "duration_max": 60,  "require_llm": false},
    {"id": "social",     "label": "📱 刷朋友圈", "weight": 8,  "duration_min": 8,  "duration_max": 20,  "require_llm": false},
    {"id": "weibo_browse", "label": "📱 逛微博",  "weight": 8,  "duration_min": 15, "duration_max": 40,  "require_llm": true},
    {"id": "xhs_browse",   "label": "📕 逛小红书", "weight": 8,  "duration_min": 15, "duration_max": 40,  "require_llm": true},
    {"id": "zhihu_browse", "label": "🔵 逛知乎", "weight": 8,  "duration_min": 15, "duration_max": 40,  "require_llm": true},
    {"id": "xueqiu_browse", "label": "🟡 逛雪球", "weight": 8,  "duration_min": 15, "duration_max": 40,  "require_llm": true},
    {"id": "cleaning",   "label": "🧹 收拾房间", "weight": 4,  "duration_min": 15, "duration_max": 30,  "require_llm": false},
    {"id": "takeout",    "label": "🍜 叫外卖", "weight": 6,  "duration_min": 8,  "duration_max": 20,  "require_llm": false},
    {"id": "nap",        "label": "💤 补觉",   "weight": 6,  "duration_min": 20, "duration_max": 60,  "require_llm": false},
    {"id": "daydream",   "label": "🌙 发呆",   "weight": 10, "duration_min": 8,  "duration_max": 30,  "require_llm": false},
    {"id": "sleep",      "label": "😴 睡觉",   "weight": 0,  "duration_min": 120, "duration_max": 360, "require_llm": false},
    {"id": "emo",        "label": "🌧️ emo",   "weight": 3,  "duration_min": 10, "duration_max": 30,  "require_llm": false},
    {"id": "thinking",   "label": "💡 思考",   "weight": 6,  "duration_min": 10, "duration_max": 30,  "require_llm": false}
  ],
  "time_modifiers": {
    "sleep":      {"after_hour": 23, "weight_bonus": 80},
    "gaming":     {"after_hour": 18, "weight_bonus": 15},
    "drama":      {"after_hour": 19, "weight_bonus": 10},
    "nap":        {"hour_range": [13, 15], "weight_bonus": 25}
  },
  "unread_bonus": {
    "target": "reading",
    "per_article_weight": 3
  },
  "browse_bonus": {
    "targets": ["weibo_browse", "xhs_browse", "zhihu_browse", "xueqiu_browse"],
    "per_platform_weight": 2
  },
  "cooldown": {
    "max_repeat": 2
  }
}

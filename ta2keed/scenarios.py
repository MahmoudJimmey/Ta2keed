"""Scripted demo conversations (used by the simulator, tests and the dashboard 'Run demo' button)."""

SCENARIOS = {
    "happy_path": {
        "title": "Messy Franco/Arabic order -> upsell -> confirmed -> shipped",
        "user": "demo-mona",
        "steps": [
            {"text": "مساء الخير عايزة العباية الكريب مقاس L لونها اسود"},
            {"text": "اسمي منى سامي ورقمي 01011112222"},
            {"text": "العنوان مدينة نصر شارع عباس العقاد عمارة 12 الدور 4 شقة 8"},
            {"text": "ضيفي"},
            {"text": "بيج"},
            {"text": "تمام"},
        ],
    },
    "risky_deposit": {
        "title": "Risky first-time order -> InstaPay deposit -> fake screenshot caught -> real one accepted",
        "user": "demo-new",
        "steps": [
            {"text": "عايزة 2 فستان صيفي مقاس M بينك وشنطة كروس سودا"},
            {"text": "انا اسمي ريم عادل 01288889999 العنوان فيصل"},
            {"text": "جنب الجامع الكبير"},
            {"text": "لا شكرا"},
            {"text": "تمام بس ممكن هفكر لو الخامة مش حلوة"},
            {"image": "receipt_wrong_account.png"},
            {"image": "receipt_ok.png"},
        ],
    },
    "known_refuser": {
        "title": "Customer with 3 past refusals -> deposit required -> customer cancels (return fee saved)",
        "user": "demo-heba",
        "steps": [
            {"text": "عايزة طقم بيتي XL كحلي"},
            {"text": "هبة علي 01233334444 المنصورة شارع الجمهورية عمارة 5 الدور 2"},
            {"text": "لا"},
            {"text": "تمام"},
            {"text": "لا مش هحول عربون"},
            {"text": "الغي"},
        ],
    },
    "questions": {
        "title": "Customer asks questions first (shipping, sizes) then orders",
        "user": "demo-q",
        "steps": [
            {"text": "الشحن للإسكندرية بكام؟"},
            {"text": "والطرحة الشيفون بكام والوانها ايه؟"},
            {"text": "خلاص عايزة طرحة شيفون بيج"},
            {"text": "سارة محمود"},
            {"text": "01055556666"},
            {"text": "اسكندرية سموحة شارع فوزي معاذ برج النور الدور 7 شقة 21"},
            {"text": "تمام"},
        ],
    },
}

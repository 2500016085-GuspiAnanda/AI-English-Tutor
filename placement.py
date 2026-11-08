"""Tes penempatan: 5 soal pilihan ganda statis, dinilai kode (deterministik, tanpa LLM).

Soal disusun makin sulit: 1-2 dasar, 3-4 menengah, 5 lanjut.
"""

QUESTIONS = [
    {"soal": "She ___ a student at Universitas Gadjah Mada.",
     "opsi": ["am", "is", "are", "be"], "jawaban": "b", "pola": "to be"},
    {"soal": "Yesterday I ___ to the library after class.",
     "opsi": ["go", "goes", "went", "going"], "jawaban": "c", "pola": "simple past"},
    {"soal": "I ___ in Jakarta since 2020.",
     "opsi": ["live", "lived", "have lived", "am living"], "jawaban": "c", "pola": "present perfect"},
    {"soal": "If I ___ more time, I would join the debate club.",
     "opsi": ["have", "had", "will have", "having"], "jawaban": "b", "pola": "second conditional"},
    {"soal": "By the time the lecturer arrived, the students ___ the discussion.",
     "opsi": ["already started", "have already started", "had already started", "were already start"],
     "jawaban": "c", "pola": "past perfect"},
]
LETTERS = ("a", "b", "c", "d")  # tuple, bukan string: "ab" in "abcd" bernilai True


def score_to_level(score: int) -> str:
    if score <= 2:
        return "pemula"
    if score <= 4:
        return "menengah"
    return "lanjut"


def grade(answers: list[str]) -> tuple[int, str]:
    """Nilai jawaban (huruf a-d) -> (skor, level). Dipisah dari I/O agar mudah diuji."""
    score = sum(a == q["jawaban"] for a, q in zip(answers, QUESTIONS))
    return score, score_to_level(score)


def run_placement(input_fn=input, print_fn=print) -> tuple[int | None, str]:
    """Jalankan tes di CLI. Kembalikan (skor, level); skor None jika memilih mulai dari nol."""
    print_fn("\n=== Tes penempatan ===")
    print_fn("5 soal pilihan ganda untuk menentukan levelmu.")
    choice = ""
    while choice not in ("t", "n"):
        choice = input_fn("Ikut tes (t) atau mulai dari nol sebagai pemula (n)? ").strip().lower()
    if choice == "n":
        return None, "pemula"

    answers = []
    for i, q in enumerate(QUESTIONS, 1):
        print_fn(f"\n{i}. {q['soal']}")
        for letter, opsi in zip(LETTERS, q["opsi"]):
            print_fn(f"   {letter}) {opsi}")
        ans = ""
        while ans not in LETTERS:
            ans = input_fn("Jawaban (a/b/c/d): ").strip().lower()
        answers.append(ans)

    score, level = grade(answers)
    print_fn(f"\nSkor: {score}/{len(QUESTIONS)} -> level: {level}")
    return score, level

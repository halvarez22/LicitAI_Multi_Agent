import re

def _normalize(text):
    if not text: return ""
    t = text.lower()
    t = t.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    t = re.sub(r'[¿?¡!,.]', '', t)
    return t.strip()

def _evaluate_clarification_intent(query):
    if not query: return False
    q = _normalize(query)
    
    strong_patterns = [
        r"que\s+(falta|faltan|falte)",
        r"cual(es)?\s+(son|es|pides|pediste|necesitas)",
        r"repite(me)?\s+(lo|los)",
        r"que\s+conceptos",
        r"que\s+concepto",
        r"que\s+datos",
        r"que\s+dato",
        r"que\s+precios",
        r"que\s+precio",
        r"que\s+me\s+pediste",
        r"aclarame",
        r"no\s+se\s+a\s+que",
        r"de\s+que\s+hablas"
    ]
    
    for p in strong_patterns:
        if re.search(p, q): return True
        
    signals_a = ["que", "cuales", "cual", "no se", "no entiendo", "dime", "explica", "cuales son"]
    signals_b = ["conceptos", "concepto", "datos", "dato", "precios", "precio", "faltan", "faltante", "requieres", "necesitas", "pediste"]
    
    has_a = any(s in q for s in signals_a)
    has_b = any(s in q for s in signals_b)
    
    if has_a and has_b: return True
    
    if len(q.split()) <= 4:
        keywords = ["conceptos", "concepto", "que conceptos", "que concepto", "cuales son", "que falta"]
        if any(k in q for k in keywords): return True

    return False

# UNIT TESTS
test_cases = [
    ("ok, que conceptos son?", True),
    ("no se a que conceptos tecnicos se refiere", True),
    ("¿Aclárame lo que falta?", True),
    ("Repíteme los precios", True),
    ("qué falta", True),
    ("que solvencia piden?", False), # DEBE SER QUERY
    ("cuanto cuesta el servicio", False), # DEBE SER QUERY
    ("ok cual concepto es", True),
]

print("--- TESTING ROUTER (V2) ---")
failures = 0
for msg, expected in test_cases:
    res = _evaluate_clarification_intent(msg)
    status = "✅ PASS" if res == expected else "❌ FAIL"
    if res != expected: failures += 1
    print(f"{status} | Input: '{msg}' | Result: {res} | Expected: {expected}")

if failures == 0:
    print("\n🚀 100% SUCCESS! El router está blindado.")
else:
    print(f"\n⚠️ FAILED {failures} tests.")

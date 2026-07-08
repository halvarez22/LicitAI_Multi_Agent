import json

with open(r'C:\Users\halva\.gemini\antigravity\brain\929791c3-af25-450c-b48d-612bfdf94982\.system_generated\logs\overview.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    line_212 = lines[211]
    data = json.loads(line_212)
    with open('previous_list.txt', 'w', encoding='utf-8') as f2:
        f2.write(data['content'])
    print("Content saved to previous_list.txt")

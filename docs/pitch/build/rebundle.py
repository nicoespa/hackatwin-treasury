"""Rebuild the deck bundle: original loader + manifest, with a new template (markup+logic)."""
import json, re, sys
from pathlib import Path
here = Path(__file__).parent
orig = (here / 'original.html').read_text()
head = (here / 'template.html').read_text()
cut = head.find('</helmet>')
template = head[:cut] + (here / sys.argv[2]).read_text() + (here / sys.argv[3]).read_text()
enc = json.dumps(template, ensure_ascii=False).replace('</', '<\\u002F')
m = re.search(r'(<script type="__bundler/template">\s*)(.*?)(\s*</script>)', orig, re.S)
out = orig[:m.start(2)] + enc + orig[m.end(2):]
out = out.replace('Presentación producto hackathon (Copy)', sys.argv[4] if len(sys.argv) > 4 else 'Prefoundly Keynote')
(here / sys.argv[1]).write_text(out)
print('wrote', sys.argv[1], len(out))

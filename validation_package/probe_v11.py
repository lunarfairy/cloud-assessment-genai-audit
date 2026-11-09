
import json,sys,os
sys.path.insert(0,os.path.abspath('.'))
from gvlib import grade_file, summarise
man=json.load(open('cases/v11_probes/manifest.json'))
out={}
for tag,cd in [('archived',None),('tier1',os.path.abspath('patched_copy/tier1')),('v11',os.path.abspath('patched_copy/v11'))]:
    pass
tag=sys.argv[1]; cd=None if tag=='archived' else os.path.abspath('../graders/v1.1a' if tag=='v11' else 'patched_copy/'+tag)
for c in man:
    gr=grade_file(c['task'],c['path'],checker_dir=cd)
    s=summarise(c['task'],gr)
    out[c['id']]=dict(accepted=s['accepted'],failed=[k for k,v in gr['checks'].items() if not v[0]],lint=gr['lint_errors'])
json.dump(out,open('cases/v11_probes/res_%s.json'%tag,'w'),indent=1)

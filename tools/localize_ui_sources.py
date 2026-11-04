"""Mark interface literals while retaining source comments and formatted data.

Developer migration tool, not part of application startup. Re-running is safe.
"""
import argparse
import ast
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
CJK=re.compile('[\u3400-\u9fff]')
FILES=[*sorted((ROOT/'app/ui').glob('*.py')),*sorted((ROOT/'app/web_follow').glob('*.py')),
       ROOT/'app/speech/runtime.py',ROOT/'app/speech/system.py']


def mark(path):
    raw=path.read_bytes();source=raw.decode('utf-8-sig');tree=ast.parse(source);lines=source.encode().splitlines(keepends=True)
    starts=[0]
    for line in lines:starts.append(starts[-1]+len(line))
    edits=[]
    def span(node):return starts[node.lineno-1]+node.col_offset,starts[node.end_lineno-1]+node.end_col_offset
    class Marker(ast.NodeVisitor):
        depth=0
        def visit_FunctionDef(self,node):
            self.depth+=1
            for item in node.body:
                if not (isinstance(item,ast.Expr) and isinstance(item.value,ast.Constant) and isinstance(item.value.value,str)):self.visit(item)
            self.depth-=1
        visit_AsyncFunctionDef=visit_FunctionDef
        def visit_Call(self,node):
            if isinstance(node.func,ast.Name) and node.func.id=='_tr':return
            self.generic_visit(node)
        def visit_JoinedStr(self,node):
            if not self.depth:return
            import copy
            value=copy.deepcopy(node);changed=False
            for i,part in enumerate(value.values):
                if isinstance(part,ast.Constant) and isinstance(part.value,str) and CJK.search(part.value):
                    value.values[i]=ast.FormattedValue(ast.Call(ast.Name('_tr',ast.Load()),[part],[]),-1,None);changed=True
                elif isinstance(part,ast.FormattedValue):
                    # Nested constant UI expressions are translated separately by
                    # the same transformer, never the values interpolated at runtime.
                    class Nested(ast.NodeTransformer):
                        def visit_Constant(self,item):
                            if isinstance(item.value,str) and CJK.search(item.value):return ast.Call(ast.Name('_tr',ast.Load()),[item],[])
                            return item
                    value.values[i]=Nested().visit(part)
                    changed=changed or ast.dump(value.values[i])!=ast.dump(part)
            if changed:
                begin,end=span(node);edits.append((begin,end,ast.unparse(ast.fix_missing_locations(value)).encode()))
        def visit_Constant(self,node):
            if self.depth and isinstance(node.value,str) and CJK.search(node.value):
                begin,end=span(node);edits.append((begin,end,b'_tr('+source.encode()[begin:end]+b')'))
    Marker().visit(tree)
    if not edits:return 0
    data=source.encode()
    for begin,end,replacement in sorted(edits,reverse=True):data=data[:begin]+replacement+data[end:]
    updated=data.decode()
    if not re.search(r'from app.i18n import .*\b_tr\b',updated):
        parsed=ast.parse(updated);futures=[n.end_lineno for n in parsed.body if isinstance(n,ast.ImportFrom) and n.module=='__future__']
        rows=updated.splitlines(keepends=True);index=max(futures) if futures else (1 if rows and rows[0].startswith(('"""',"'''")) and rows[0].rstrip().endswith(('"""',"'''")) else 0)
        rows.insert(index,'from app.i18n import tr as _tr\n');updated=''.join(rows)
    ast.parse(updated);path.write_text(updated,encoding='utf-8',newline='')
    return len(edits)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');parser.add_argument('--inventory',type=Path,required=True);args=parser.parse_args()
    inventory=set()
    extra=[ROOT/'app/languages.py',ROOT/'app/speech/config.py',ROOT/'app/subtitles/transcript.py']
    for path in [*FILES,*extra]:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and CJK.search(node.value):inventory.add(node.value)
    args.inventory.parent.mkdir(parents=True,exist_ok=True)
    args.inventory.write_text(json.dumps(sorted(inventory),ensure_ascii=False,indent=2),encoding='utf-8')
    if args.apply:
        for path in FILES:
            count=mark(path)
            if count:print(path.relative_to(ROOT),count)


if __name__=='__main__':main()

#!/usr/bin/env python3
"""Read a bundled Indiana Constitution provision."""
import argparse, json, re
from html.parser import HTMLParser
from pathlib import Path
from corpus import ensure_corpus
ROOT=ensure_corpus("in-laws")/'Constitution'
class P(HTMLParser):
 def __init__(self,target): super().__init__(); self.target=target; self.active=False; self.pre=False; self.buf=[]
 def handle_starttag(self,t,a):
  if t=='article' and dict(a).get('id')==self.target: self.active=True
  if self.active and t=='pre': self.pre=True
 def handle_endtag(self,t):
  if t=='pre': self.pre=False
  if t=='article' and self.active: self.active=False
 def handle_data(self,d):
  if self.active and self.pre: self.buf.append(d)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('citation'); ap.add_argument('--format',choices=['text','json'],default='text'); a=ap.parse_args()
 nums=re.findall(r'(?i)(?:article|art\.?)\s*([IVXLCDM]+|\d+).*?(?:section|sec\.?|§)\s*(\d+[A-Za-z]?)',a.citation)
 if not nums: raise SystemExit("Expected e.g. 'Article 1, Section 9'")
 art,sec=nums[0]; key=f'article-{art.lower()}-section-{sec.lower()}'; data=json.loads((ROOT/'index.json').read_text()); e=data['provisions'].get(key)
 if not e: raise SystemExit(f'Constitution provision not found: {a.citation}')
 p=P(e['anchor']); p.feed((ROOT/e['path']).read_text()); text=''.join(p.buf)
 print(json.dumps({**e,'text':text},indent=2) if a.format=='json' else e['citation']+'\n'+text)
if __name__=='__main__': main()

// UI documents only. Never apply this to course pages or subtitle content.
(function(scope){
  'use strict';let language=(scope.__eltUiLanguage||scope.document?.documentElement?.dataset?.eltUiLanguage)==='en'?'en':'zh';const originals=new WeakMap();
  const catalogue=scope.__ELT_ENGLISH_UI||{},fragments=Object.keys(catalogue).filter(s=>/[\u3400-\u9fff]/.test(s)).sort((a,b)=>b.length-a.length);
  function text(value){
    if(language!=='en'||typeof value!=='string')return value;
    if(Object.hasOwn(catalogue,value))return catalogue[value];
    let result=value;for(const key of fragments)if(result.includes(key))result=result.split(key).join(catalogue[key]);return result;
  }
  function translateDocument(root=document){
    const doc=root.ownerDocument||root;
    const walker=doc.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
      const node=walker.currentNode,parent=node.parentElement;
      if(!parent||parent.closest('script,style,[data-elt-content],#o,#t,#original,#translation'))continue;
      const previous=originals.get(node),source=previous?.rendered===node.nodeValue?previous.source:node.nodeValue;
      const rendered=text(source);originals.set(node,{source,rendered});if(node.nodeValue!==rendered)node.nodeValue=rendered;
    }
    for(const node of root.querySelectorAll('[title],[placeholder],[aria-label]')){
      const saved=originals.get(node)||{};
      for(const key of ['title','placeholder','aria-label'])if(node.hasAttribute(key)){
        const current=node.getAttribute(key),old=saved[key],source=old?.rendered===current?old.source:current;
        const rendered=text(source);saved[key]={source,rendered};if(current!==rendered)node.setAttribute(key,rendered);
      }
      originals.set(node,saved);
    }
    if(root===document)document.documentElement.lang=language==='en'?'en':'zh-CN';
  }
  scope.ELTLocale={text,translateDocument,setLanguage(value){language=value==='en'?'en':'zh';},get language(){return language;}};
})(globalThis);

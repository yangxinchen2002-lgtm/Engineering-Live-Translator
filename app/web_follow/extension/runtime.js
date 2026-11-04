// sendMessage can throw before returning a Promise after extension reload.
(function(scope){
  'use strict';
  function createMessenger(runtime,onInvalidated=()=>{}){
    let valid=true;
    const missing=()=>{try{return !runtime?.id;}catch{return true;}};
    return {
      get valid(){return valid;},
      async send(message){
        if(!valid)throw Error('Extension context invalidated.');
        try{
          if(missing())throw Error('Extension context invalidated.');
          return await runtime.sendMessage(message);
        }catch(error){
          if(valid&&(missing()||/extension context invalidated/i.test(error?.message||''))){
            valid=false;onInvalidated();
          }
          throw error;
        }
      }
    };
  }
  scope.ELTRuntime={createMessenger};
})(globalThis);

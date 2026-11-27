// Apply the saved light/dark choice before the page paints.
try{const t=localStorage.getItem('coldmap-theme');if(t)document.documentElement.dataset.theme=t}catch(e){}

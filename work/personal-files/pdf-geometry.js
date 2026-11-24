export function geometry({width,height,appZoom=1,zoom=1,pdf}) {
  const viewportWidth=width/appZoom;
  const viewportHeight=Math.max(120,height/appZoom-106);
  const pageWidth=Math.max(300,viewportWidth-30)*zoom;
  const pageHeight=pdf?pageWidth*pdf.height/pdf.width:0;
  return {width:pageWidth,height:pageHeight,viewportWidth,viewportHeight,maxX:Math.max(0,pageWidth+24-viewportWidth),maxY:Math.max(0,pageHeight+24-viewportHeight)};
}

export function wheelPosition(position,event,g,appZoom=1) {
  const d=event.delta_lines?{x:event.delta_lines.x*28,y:event.delta_lines.y*28}:event.delta||{x:0,y:0};
  const horizontal=event.modifiers?.shift&&!d.x;
  return {x:Math.max(0,Math.min(g.maxX,(position.x||0)-(horizontal?d.y:d.x)/appZoom)),y:Math.max(0,Math.min(g.maxY,(position.y||0)-(horizontal?0:d.y)/appZoom))};
}

export function hitChar(chars,x,y,strict=false) {
  let nearest=-1,score=Infinity;
  for(let i=0;i<chars.length;i++) {
    const r=chars[i].r;
    if(!r||!chars[i].t.trim())continue;
    const dx=Math.max(r[0]-x,0,x-r[2]),dy=Math.max(r[1]-y,0,y-r[3]);
    const distance=dx*dx+dy*dy*4;
    if(distance<score){score=distance;nearest=i;}
  }
  return strict&&score>0.0004?-1:nearest;
}

export function selectedText(chars,anchor,focus) {
  if(anchor<0||focus<0)return '';
  return chars.slice(Math.min(anchor,focus),Math.max(anchor,focus)+1).map(c=>c.t).join('').replace(/\r/g,'');
}

export function selectionRects(chars,anchor,focus) {
  if(anchor<0||focus<0)return [];
  const result=[];
  for(const ch of chars.slice(Math.min(anchor,focus),Math.max(anchor,focus)+1)) {
    const r=ch.r;if(!r||!ch.t.trim())continue;
    const previous=result.at(-1);
    if(previous&&Math.abs(previous[1]-r[1])<Math.max(.003,(r[3]-r[1])*.35)&&r[0]>=previous[0]&&r[0]-previous[2]<.03) {
      previous[2]=Math.max(previous[2],r[2]);previous[3]=Math.max(previous[3],r[3]);
    } else result.push([...r]);
  }
  return result;
}

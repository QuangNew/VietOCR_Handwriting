export function outline(points,shape,angle=0){
  if(!Number.isFinite(angle)||Math.abs(angle)>180||points.length>4096||points.some(p=>p.length!==2||p.some(n=>!Number.isFinite(n))))throw Error('Vùng crop không hợp lệ');
  if(points.length<2)return[];
  let polygon=points;
  if(shape!=='freehand'){
    const [a,b]=[points[0],points.at(-1)],l=Math.min(a[0],b[0]),r=Math.max(a[0],b[0]),t=Math.min(a[1],b[1]),bt=Math.max(a[1],b[1]);
    polygon=shape==='ellipse'?Array.from({length:96},(_,i)=>[(l+r)/2+(r-l)/2*Math.cos(i*Math.PI/48),(t+bt)/2+(bt-t)/2*Math.sin(i*Math.PI/48)]):[[l,t],[r,t],[r,bt],[l,bt]];
  }
  if(!angle)return polygon;
  const x=polygon.map(p=>p[0]),y=polygon.map(p=>p[1]),cx=(Math.min(...x)+Math.max(...x))/2,cy=(Math.min(...y)+Math.max(...y))/2,c=Math.cos(angle*Math.PI/180),s=Math.sin(angle*Math.PI/180);
  return polygon.map(([x,y])=>[cx+c*(x-cx)-s*(y-cy),cy+s*(x-cx)+c*(y-cy)]);
}
export function bounds(points,width,height){
  if(points.length<3)throw Error('Vẽ vùng kín trước khi crop');
  const x=points.map(p=>p[0]),y=points.map(p=>p[1]),l=Math.floor(Math.min(...x)),t=Math.floor(Math.min(...y)),r=Math.ceil(Math.max(...x)),b=Math.ceil(Math.max(...y));
  if(l<0||t<0||r>width||b>height||r-l<2||b-t<2)throw Error('Vùng crop rỗng hoặc vượt mép ảnh');return {l,t,w:r-l,h:b-t};
}
export function draftOnlyAction(action){return ['import','capture','crop','blackWhite','rotate'].includes(action);}

self.onmessage=async({data:blob})=>{
  try{
    const image=await createImageBitmap(blob),canvas=new OffscreenCanvas(image.width,image.height),c=canvas.getContext('2d',{willReadFrequently:true});c.drawImage(image,0,0);image.close();
    const data=c.getImageData(0,0,canvas.width,canvas.height),p=data.data,w=canvas.width,h=canvas.height,gray=new Uint8Array(w*h),sums=new Uint32Array(w),radius=15;
    for(let i=0;i<gray.length;i++){const at=i*4,a=p[at+3]/255;gray[i]=Math.round((p[at]*.299+p[at+1]*.587+p[at+2]*.114)*a+255*(1-a));}
    for(let y=0;y<=Math.min(radius,h-1);y++)for(let x=0;x<w;x++)sums[x]+=gray[y*w+x];
    for(let y=0;y<h;y++){let sum=0;for(let x=0;x<=Math.min(radius,w-1);x++)sum+=sums[x];const rows=Math.min(h-1,y+radius)-Math.max(0,y-radius)+1;
      for(let x=0;x<w;x++){const cols=Math.min(w-1,x+radius)-Math.max(0,x-radius)+1,v=gray[y*w+x]<sum/(rows*cols)-8?0:255,i=(y*w+x)*4;p[i]=p[i+1]=p[i+2]=v;p[i+3]=255;if(x-radius>=0)sum-=sums[x-radius];if(x+radius+1<w)sum+=sums[x+radius+1];}
      for(let x=0;x<w;x++){if(y-radius>=0)sums[x]-=gray[(y-radius)*w+x];if(y+radius+1<h)sums[x]+=gray[(y+radius+1)*w+x];}}
    c.putImageData(data,0,0);self.postMessage({blob:await canvas.convertToBlob({type:'image/png'})});
  }catch(e){self.postMessage({error:String(e)});}
};

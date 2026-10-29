// User-confirmed experience selection: width -> perimeter -> box surface area.
// Price/weight scaling is deliberately left to the existing callers.
const dimensions=value=>['width','height','depth'].map(axis=>{
  const number=Number(value[axis+'_mm']??value['reference_'+axis+'_mm']);
  if(!Number.isFinite(number)||number<=0)throw new Error('经验匹配尺寸必须为有效正数');
  return number;
});
export function experienceDimensionRank(reference,target){
  const [w,h,d]=dimensions(reference),[tw,th,td]=dimensions(target);
  return [Math.abs(w-tw),Math.abs(w+h+d-tw-th-td),
    Math.abs(2*(w*h+w*d+h*d)-2*(tw*th+tw*td+th*td)),
    (w-tw)**2+(h-th)**2+(d-td)**2];
}
export function compareExperienceDimensions(a,b,target){
  const x=experienceDimensionRank(a,target),y=experienceDimensionRank(b,target);
  // Preserve the former 3D-distance tie-breaker after all three criteria.
  return x[0]-y[0]||x[1]-y[1]||x[2]-y[2]||x[3]-y[3];
}

/** Horizontal reflection of the view, with coordinates kept in the source frame. */
export const displayX=(x,width,mirrored)=>mirrored?width-x:x;
export const imageX=(x,width,mirrored)=>mirrored?width-x:x;

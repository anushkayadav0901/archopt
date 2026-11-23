export const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
export async function api(path:string, options:RequestInit = {}){
 const response=await fetch(`${API}${path}`,{headers:{'Content-Type':'application/json',...(options.headers||{})},cache:'no-store',...options});
 if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||'Request failed');}
 return response.status===204?null:response.json();
}
export type Room={id?:number;name:string;room_type?:string;required_area:number;min_width:number;min_height:number;preferred_width?:number;preferred_height?:number;priority?:string};
export type Project={id:number;name:string;project_type:string;plot_width:number;plot_height:number;plot_area:number;status:string;created_at:string;room_count:number;layout_count:number;rooms:Room[];relationships:any[]};
export type Layout={id:number;project_id:number;name:string;plan:{rooms:any[]};metrics:{efficiency:number;adjacency:number;circulation:number;accessibility:number;cost:number;violations:string[]};selected:boolean};

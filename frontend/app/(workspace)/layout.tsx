'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Shell from '../../components/Shell';
export default function WorkspaceLayout({children}:{children:React.ReactNode}){const router=useRouter();useEffect(()=>{if(!localStorage.getItem('archopt-auth'))router.replace('/login')},[router]);return <Shell>{children}</Shell>}

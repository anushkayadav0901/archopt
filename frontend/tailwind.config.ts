import type { Config } from 'tailwindcss';
export default { content:['./app/**/*.{ts,tsx}','./components/**/*.{ts,tsx}'], theme:{extend:{colors:{navy:'#172554',ink:'#1E293B',muted:'#64748B',line:'#E2E8F0',wash:'#F8FAFC',accent:'#4F46E5'}}}, plugins:[] } satisfies Config;

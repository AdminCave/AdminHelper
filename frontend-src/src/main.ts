import './styles/global.css';
import { mount } from 'svelte';
import App from './App.svelte';

const target = document.getElementById('app');
if (!target) {
  throw new Error('#app mount target missing in index.html');
}

const app = mount(App, { target });
export default app;

import * as THREE from '/static/vendor/three.module.js';
import { GLTFLoader } from '/static/vendor/GLTFLoader.js';

let disposeCursor = null;

function initAerixCursor(mode = 'landing') {
  const isLanding = mode === 'landing';
  if (disposeCursor || (isLanding && !document.querySelector('.aerix-start-page')) || (!isLanding && !document.querySelector('.main-content'))) return;
  if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;

  const host = document.createElement('div');
  const size = isLanding ? 108 : 58;
  host.className = `aerix-3d-cursor aerix-3d-cursor--${mode}`;
  host.style.width = `${size}px`; host.style.height = `${size}px`;
  host.setAttribute('aria-hidden', 'true');
  document.body.append(host);
  document.body.classList.add('aerix-cursor-active');

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.className = 'aerix-3d-cursor-canvas';
  host.append(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(31, 1, 0.1, 100);
  camera.position.set(0, 0.4, 15);
  scene.add(new THREE.HemisphereLight(0xe0e5ff, 0x080311, 2.8));
  const key = new THREE.DirectionalLight(0xffffff, 3.2); key.position.set(-5, 8, 10); scene.add(key);
  const purple = new THREE.PointLight(0xa462ff, 21, 24); purple.position.set(-4, 1, 7); scene.add(purple);
  const cyan = new THREE.PointLight(0x25caff, 18, 24); cyan.position.set(4, -1, 7); scene.add(cyan);
  const rig = new THREE.Group(), tilt = new THREE.Group(); rig.add(tilt); scene.add(rig);

  let frame = 0, alive = true, visible = false, pressed = false, interactive = false;
  // These are browser viewport coordinates from the actual OS pointer event.
  // PyAutoGUI moves that OS pointer and clicks at its current position, so the
  // visual cursor must use this exact pair without a display-only offset or
  // a second smoothing path.
  let finalCursorX = -120, finalCursorY = -120;
  let velocityX = 0, velocityY = 0, targetTiltX = 0, targetTiltY = 0;
  const resize = () => renderer.setSize(size, size, false);
  resize();
  new GLTFLoader().load('/static/assets/aerix-3d-start-mouse.glb', (gltf) => {
    const model = gltf.scene, bounds = new THREE.Box3().setFromObject(model);
    model.position.sub(bounds.getCenter(new THREE.Vector3())); model.scale.setScalar(0.47);
    model.traverse((child) => { if (!child.isMesh) return; const materials = Array.isArray(child.material) ? child.material : [child.material]; materials.forEach((material) => { if (!material) return; material.roughness = Math.min(material.roughness ?? 0.4, 0.46); material.metalness = Math.max(material.metalness ?? 0, 0.17); material.envMapIntensity = 1.3; material.needsUpdate = true; }); });
    tilt.add(model); visible = true;
  });
  const isInteractive = (event) => { const element = document.elementFromPoint(event.clientX, event.clientY); return !!element?.closest('button,a[href],input,select,textarea,[role="button"],[tabindex]:not([tabindex="-1"])'); };
  const move = (event) => { const nextVX = event.movementX || event.clientX - finalCursorX; const nextVY = event.movementY || event.clientY - finalCursorY; finalCursorX = event.clientX; finalCursorY = event.clientY; velocityX = THREE.MathUtils.lerp(velocityX, nextVX, 0.35); velocityY = THREE.MathUtils.lerp(velocityY, nextVY, 0.35); targetTiltY = THREE.MathUtils.clamp(-velocityX * 0.045, -0.42, 0.42); targetTiltX = THREE.MathUtils.clamp(velocityY * 0.035, -0.3, 0.3); host.style.transform = `translate3d(${finalCursorX - size / 2}px,${finalCursorY - size / 2}px,0)`; interactive = isInteractive(event); host.classList.toggle('is-interactive', interactive); };
  const down = () => { pressed = true; host.classList.add('is-clicking'); };
  const up = () => { pressed = false; window.setTimeout(() => host.classList.remove('is-clicking'), 105); };
  window.addEventListener('pointermove', move, { passive: true }); window.addEventListener('pointerdown', down, { passive: true }); window.addEventListener('pointerup', up, { passive: true });
  const animate = (time) => { if (!alive) return; frame = requestAnimationFrame(animate); if (visible) { tilt.rotation.x = THREE.MathUtils.lerp(tilt.rotation.x, targetTiltX + (pressed ? 0.15 : 0), 0.12); tilt.rotation.y = THREE.MathUtils.lerp(tilt.rotation.y, targetTiltY, 0.12); tilt.rotation.z = THREE.MathUtils.lerp(tilt.rotation.z, -velocityX * 0.018, 0.1); const scale = pressed ? 0.9 : interactive ? 1.1 : 1; tilt.scale.lerp(new THREE.Vector3(scale, scale, scale), 0.16); rig.position.y = Math.sin(time * 0.003) * 0.09 + (interactive ? 0.1 : 0); velocityX *= 0.91; velocityY *= 0.91; renderer.render(scene, camera); } };
  frame = requestAnimationFrame(animate);
  disposeCursor = () => { alive = false; cancelAnimationFrame(frame); window.removeEventListener('pointermove', move); window.removeEventListener('pointerdown', down); window.removeEventListener('pointerup', up); scene.traverse((child) => { child.geometry?.dispose?.(); const materials = Array.isArray(child.material) ? child.material : [child.material]; materials.forEach((material) => material?.dispose?.()); }); renderer.dispose(); host.remove(); document.body.classList.remove('aerix-cursor-active'); disposeCursor = null; };
}

window.initAerixCursor = initAerixCursor;
window.initAerixDashboardCursor = () => initAerixCursor('dashboard');
window.destroyAerixCursor = () => disposeCursor?.();
initAerixCursor();

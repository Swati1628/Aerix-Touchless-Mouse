import * as THREE from '/static/vendor/three.module.js';
import { GLTFLoader } from '/static/vendor/GLTFLoader.js';

let disposeStartMouse = null;

function initAerixStartMouse() {
  if (disposeStartMouse) return;
  const stage = document.querySelector('.aerix-start-mouse');
  if (!stage) return;

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.className = 'aerix-start-model';
  renderer.domElement.setAttribute('aria-hidden', 'true');
  stage.append(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 1.5, 25);
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  scene.add(new THREE.HemisphereLight(0xc9d7ff, 0x05020d, 2.25));
  const key = new THREE.DirectionalLight(0xe2e7ff, 3.5); key.position.set(-9, 13, 16); key.castShadow = true; scene.add(key);
  const violetRim = new THREE.PointLight(0x9a58ff, 35, 42); violetRim.position.set(-9, 3, 8); scene.add(violetRim);
  const cyanRim = new THREE.PointLight(0x20beff, 32, 38); cyanRim.position.set(9, 1, 11); scene.add(cyanRim);
  const underGlow = new THREE.PointLight(0x573cff, 22, 25); underGlow.position.set(0, -5, 3); scene.add(underGlow);

  const rig = new THREE.Group(), orbit = new THREE.Group(), tilt = new THREE.Group();
  orbit.add(tilt); rig.add(orbit); scene.add(rig);
  const halo = new THREE.Mesh(new THREE.CircleGeometry(5.7, 64), new THREE.MeshBasicMaterial({ color: 0x6e50ff, transparent: true, opacity: 0.13, blending: THREE.AdditiveBlending, depthWrite: false }));
  halo.scale.y = 0.28; halo.rotation.x = -Math.PI / 2; halo.position.y = -3.05; scene.add(halo);

  let model = null, modelLoaded = false, hovered = false, dragging = false, pointerDown = false, moved = false, lastX = 0, lastY = 0;
  let targetYaw = 0.45, targetPitch = -0.3, targetPointerX = 0, targetPointerY = 0, frame = 0, alive = true;
  const resize = () => { const width = stage.clientWidth, height = stage.clientHeight; if (!width || !height) return; renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix(); };
  const setPointer = (event) => { const box = stage.getBoundingClientRect(); targetPointerX = ((event.clientX - box.left) / box.width - 0.5) * 2; targetPointerY = -((event.clientY - box.top) / box.height - 0.5) * 2; pointer.set(targetPointerX, targetPointerY); };
  const updateHover = () => { if (!modelLoaded || !model) return; raycaster.setFromCamera(pointer, camera); hovered = raycaster.intersectObject(model, true).length > 0; stage.classList.toggle('is-hovered', hovered); stage.style.cursor = hovered || dragging ? 'grab' : 'default'; };
  const onPointerMove = (event) => { setPointer(event); updateHover(); if (!pointerDown) return; const dx = event.clientX - lastX, dy = event.clientY - lastY; if (Math.abs(dx) + Math.abs(dy) > 1) moved = true; if (dragging) { targetYaw += dx * 0.012; targetPitch = THREE.MathUtils.clamp(targetPitch + dy * 0.007, -0.44, 0.44); } lastX = event.clientX; lastY = event.clientY; };
  const onPointerDown = (event) => { setPointer(event); updateHover(); pointerDown = true; moved = false; lastX = event.clientX; lastY = event.clientY; dragging = hovered; if (dragging) { stage.setPointerCapture?.(event.pointerId); stage.style.cursor = 'grabbing'; } };
  const onPointerUp = (event) => { if (dragging && moved) { stage.dataset.dragging = 'true'; window.setTimeout(() => delete stage.dataset.dragging, 0); } pointerDown = false; dragging = false; stage.style.cursor = hovered ? 'grab' : 'default'; try { stage.releasePointerCapture?.(event.pointerId); } catch { /* no capture */ } };
  const resetPointer = () => { targetPointerX = 0; targetPointerY = 0; hovered = false; stage.classList.remove('is-hovered'); stage.style.cursor = 'default'; };
  stage.addEventListener('pointermove', onPointerMove, { passive: true }); stage.addEventListener('pointerdown', onPointerDown); stage.addEventListener('pointerup', onPointerUp); stage.addEventListener('pointercancel', onPointerUp); stage.addEventListener('pointerleave', resetPointer, { passive: true }); window.addEventListener('resize', resize, { passive: true }); resize();

  new GLTFLoader().load('/static/assets/aerix-3d-start-mouse.glb', (gltf) => {
    model = gltf.scene; const bounds = new THREE.Box3().setFromObject(model); model.position.sub(bounds.getCenter(new THREE.Vector3())); model.scale.setScalar(1.82);
    model.traverse((child) => { if (!child.isMesh) return; child.castShadow = true; child.receiveShadow = true; const materials = Array.isArray(child.material) ? child.material : [child.material]; materials.forEach((material) => { if (!material) return; material.roughness = Math.min(material.roughness ?? 0.42, 0.48); material.metalness = Math.max(material.metalness ?? 0, 0.15); material.envMapIntensity = 1.4; material.needsUpdate = true; }); });
    tilt.add(model); modelLoaded = true;
  }, undefined, () => renderer.domElement.remove());

  const animate = (time) => { if (!alive) return; frame = requestAnimationFrame(animate); if (!modelLoaded) return; const hoverLift = hovered ? 0.34 : 0, idleYaw = dragging ? 0 : Math.sin(time * 0.00033) * 0.035; orbit.rotation.y = THREE.MathUtils.lerp(orbit.rotation.y, targetYaw + idleYaw, 0.1); orbit.rotation.x = THREE.MathUtils.lerp(orbit.rotation.x, targetPitch, 0.1); tilt.rotation.x = THREE.MathUtils.lerp(tilt.rotation.x, -targetPointerY * (hovered ? 0.09 : 0.035), 0.08); tilt.rotation.y = THREE.MathUtils.lerp(tilt.rotation.y, targetPointerX * (hovered ? 0.12 : 0.045), 0.08); const scale = hovered ? 1.045 : 1; tilt.scale.lerp(new THREE.Vector3(scale, scale, scale), 0.1); rig.position.y = Math.sin(time * 0.0011) * 0.36 + hoverLift; rig.rotation.z = Math.sin(time * 0.0007) * 0.022; halo.material.opacity = THREE.MathUtils.lerp(halo.material.opacity, hovered ? 0.24 : 0.13, 0.08); halo.scale.x = THREE.MathUtils.lerp(halo.scale.x, hovered ? 1.13 : 1, 0.08); renderer.render(scene, camera); };
  frame = requestAnimationFrame(animate);

  disposeStartMouse = () => { alive = false; cancelAnimationFrame(frame); stage.removeEventListener('pointermove', onPointerMove); stage.removeEventListener('pointerdown', onPointerDown); stage.removeEventListener('pointerup', onPointerUp); stage.removeEventListener('pointercancel', onPointerUp); stage.removeEventListener('pointerleave', resetPointer); window.removeEventListener('resize', resize); scene.traverse((child) => { if (child.geometry) child.geometry.dispose(); const materials = Array.isArray(child.material) ? child.material : [child.material]; materials.forEach((material) => material?.dispose?.()); }); renderer.dispose(); renderer.domElement.remove(); disposeStartMouse = null; };
}

window.initAerixStartMouse = initAerixStartMouse;
window.destroyAerixStartMouse = () => disposeStartMouse?.();
initAerixStartMouse();

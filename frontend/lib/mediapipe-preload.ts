import { FilesetResolver, PoseLandmarker } from '@mediapipe/tasks-vision';

const WASM_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm';
const MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task';

let _landmarker: PoseLandmarker | null = null;
let _promise: Promise<PoseLandmarker | null> | null = null;

const POSE_OPTS = {
  runningMode: 'VIDEO' as const,
  numPoses: 1,
  minPoseDetectionConfidence: 0.5,
  minPosePresenceConfidence: 0.5,
  minTrackingConfidence: 0.5,
};

export async function preloadPoseLandmarker(): Promise<PoseLandmarker | null> {
  if (_landmarker) return _landmarker;
  if (_promise) return _promise;

  _promise = (async () => {
    try {
      const vision = await FilesetResolver.forVisionTasks(WASM_URL);
      _landmarker = await PoseLandmarker.createFromOptions(vision, {
        baseOptions: { modelAssetPath: MODEL_URL, delegate: 'CPU' },
        ...POSE_OPTS,
      });
      return _landmarker;
    } catch {
      return null;
    }
  })();

  return _promise;
}

// Returns the cached instance synchronously (null if not loaded yet)
export function getCachedLandmarker(): PoseLandmarker | null {
  return _landmarker;
}

/**
 * Offline ML inference using exported ExtraTrees JSON (model_trees.json).
 */
import modelTrees from '../../assets/ml/model_trees.json';
import { FEATURE_SCHEMA } from '@/cv/analyze';

interface TreeNode {
  features: number[];
  thresholds: number[];
  children_left: number[];
  children_right: number[];
  values: number[];
}

interface MobileModel {
  model_version: string;
  feature_schema: string[];
  n_trees: number;
  trees: TreeNode[];
}

const model = modelTrees as MobileModel;

function predictTree(tree: TreeNode, x: number[]): number {
  let node = 0;
  while (tree.children_left[node] !== tree.children_right[node]) {
    const fi = tree.features[node];
    if (fi < 0) break;
    node = x[fi] <= tree.thresholds[node] ? tree.children_left[node] : tree.children_right[node];
  }
  return tree.values[node];
}

export function predictOffline(featureVector: number[]): number | null {
  if (!model?.trees?.length || featureVector.length !== FEATURE_SCHEMA.length) {
    return null;
  }
  const preds = model.trees.map((t) => predictTree(t, featureVector));
  const ppm = preds.reduce((a, b) => a + b, 0) / preds.length;
  return Math.max(0, ppm);
}

export function getOfflineModelVersion(): string {
  return model?.model_version ?? 'none';
}

export function isOfflineModelAvailable(): boolean {
  return Boolean(model?.trees?.length);
}

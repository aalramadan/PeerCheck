import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer, AutoModel
from tqdm import tqdm
import argparse
import os
import json
import numpy as np
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt
import seaborn as sns


class MultiTaskMarginModel(nn.Module):
    
    def __init__(self, model_name_or_path, num_main_classes, num_content_classes, num_style_classes, num_fine_grained_classes,
                 margin_m, scale_s, dropout_prob, cost_margin, human_class_idx, ai_class_idx):
        super(MultiTaskMarginModel, self).__init__()
        self.bert = AutoModel.from_pretrained(model_name_or_path)
        hidden_size = self.bert.config.hidden_size
        self.dropout = nn.Dropout(dropout_prob)
        

        self.num_main_classes = num_main_classes
        self.margin_m = margin_m
        self.scale_s = scale_s
        self.cost_margin = cost_margin
        self.human_class_idx = human_class_idx
        self.ai_class_idx = ai_class_idx
        self.main_classifier_weight = nn.Parameter(torch.FloatTensor(num_main_classes, hidden_size))
        nn.init.xavier_uniform_(self.main_classifier_weight)
        

        self.content_classifier = nn.Linear(hidden_size, num_content_classes)
        self.style_classifier = nn.Linear(hidden_size, num_style_classes)
        self.fine_grained_classifier = nn.Linear(hidden_size, num_fine_grained_classes)

    def forward(self, input_ids, attention_mask, main_labels=None):
        outputs = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        pooled_output = outputs.last_hidden_state[:, 0]
        pooled_output_dropped = self.dropout(pooled_output)
        

        features_normalized = F.normalize(pooled_output_dropped, p=2, dim=1) 
        weights_normalized = F.normalize(self.main_classifier_weight, p=2, dim=1)
        cosine_similarity = F.linear(features_normalized, weights_normalized)
        
        main_logits = cosine_similarity * self.scale_s
        

        content_logits = self.content_classifier(pooled_output_dropped)
        style_logits = self.style_classifier(pooled_output_dropped)
        fine_grained_logits = self.fine_grained_classifier(pooled_output_dropped)
        

        return main_logits, content_logits, style_logits, fine_grained_logits, features_normalized


class InferenceDataset(Dataset):


    def __init__(self, file_path, tokenizer, max_len, label_maps):
        self.tokenizer = tokenizer
        self.max_len = max_len
        self.main_label_map, self.content_label_map, self.style_label_map, self.fine_grained_label_map = label_maps
        self.num_content_labels = len(self.content_label_map)
        self.num_style_labels = len(self.style_label_map)
        self.data = self._load_data(file_path)

    def _load_data(self, file_path):
        data = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                data.append(json.loads(line))
        return data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, item_idx):
        item = self.data[item_idx]
        review_text = str(item.get("review", ""))
        
        class_type = item.get("class", "unknown")
        model_source_str = item.get("model", "unknown")
        fine_grained_label_str = item.get("label", "unknown")
        
        main_label_int = self.main_label_map.get(class_type, -1)
        fine_grained_label_int = self.fine_grained_label_map.get(fine_grained_label_str, -1)
        
        content_labels = torch.zeros(self.num_content_labels)
        style_labels = torch.zeros(self.num_style_labels)
        
        if model_source_str != "unknown":
            parts = model_source_str.split('_')
            content_source_names = set()
            style_source_names = set()
            if len(parts) == 1:
                model_name = parts[0]
                content_source_names.add(model_name)
                style_source_names.add(model_name)
            else: 
                content_part, style_part = parts[0], parts[1]
                if class_type == 'mix':
                    content_source_names.add(content_part)
                    content_source_names.add(style_part)
                    style_source_names.add(style_part)
                else:
                    content_source_names.add(content_part)
                    style_source_names.add(style_part)

            for source in content_source_names:
                if source in self.content_label_map:
                    content_labels[self.content_label_map[source]] = 1.0
            
            for source in style_source_names:
                if source.startswith('qwen'):
                    style_key = 'qwen'
                else:
                    style_key = source
                if style_key in self.style_label_map:
                    style_labels[self.style_label_map[style_key]] = 1.0

        encoding = self.tokenizer.encode_plus(
            review_text, add_special_tokens=True, max_length=self.max_len,
            padding='max_length', truncation=True, return_attention_mask=True, return_tensors='pt'
        )
        
        return {
            'input_ids': encoding['input_ids'].flatten(),
            'attention_mask': encoding['attention_mask'].flatten(),
            'main_labels': torch.tensor(main_label_int, dtype=torch.long),
            'content_labels': content_labels,
            'style_labels': style_labels,
            'fine_grained_labels': torch.tensor(fine_grained_label_int, dtype=torch.long)
        }


def plot_tsne_visualization(embeddings, labels, output_path, label_map):

    print("\n  Starting T-SNE dimensionality reduction... (This may take a while)")
    

    valid_indices = [i for i, label in enumerate(labels) if label != -1]
    if not valid_indices:
        print("  Warning: No valid labels found for T-SNE plot. Skipping visualization.")
        return

    embeddings = embeddings[valid_indices]
    labels = labels[valid_indices]

    tsne = TSNE(
        n_components=2, 
        perplexity=30, 
        max_iter=1000,       
        init='pca',         
        random_state=42, 
        n_jobs=-1
    )
    tsne_results = tsne.fit_transform(embeddings)
    

    idx_to_label = {v: k for k, v in label_map.items()}
    string_labels = [idx_to_label[l] for l in labels]


    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(16, 12))
    

    hue_order = ['human', 'mix', 'ai']
    palette = {'human': '#1f77b4', 'mix': '#ff7f0e', 'ai': '#d62728'} 

    sns.scatterplot(
        x=tsne_results[:, 0],
        y=tsne_results[:, 1],
        hue=string_labels,
        hue_order=hue_order,
        palette=palette,
        s=50,          
        alpha=0.7,
        ax=ax
    )
    

    legend = ax.legend(
        title='Main Task Classes',
        loc='best',
        shadow=True,
        prop={'size': 16},          
        title_fontsize='18',        
        markerscale=1.5             
    )
    
    ax.set_title('t-SNE Visualization of Main Task Embeddings', fontsize=22, pad=20)
    ax.set_xlabel('t-SNE Dimension 1', fontsize=16)
    ax.set_ylabel('t-SNE Dimension 2', fontsize=16)
    
    plt.grid(True)
    plt.tight_layout()
    

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f"  t-SNE plot saved to: {output_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run inference and visualize embeddings for a multi-task model.")
    parser.add_argument('--model_name_or_path', type=str, required=True, help='pretrained_model_path')
    parser.add_argument('--trained_model_path', type=str, required=True, help='The path to the trained model weight file (.bin)')
    parser.add_argument('--test_file', type=str, required=True, help="test.jsonl path")
    parser.add_argument('--output_file', type=str, required=True, help="Output file path with prediction results")
    parser.add_argument('--plot_path', type=str, default="tsne_visualization.png", help="Path where the t-SNE visualization result graph is saved")
    parser.add_argument('--max_len', type=int, default=2048)
    parser.add_argument('--batch_size', type=int, default=16)
    parser.add_argument('--margin_m', type=float, default=0.25)
    parser.add_argument('--scale_s', type=float, default=30.0)
    parser.add_argument('--dropout_prob', type=float, default=0.0)
    parser.add_argument('--cost_margin', type=float, default=0.25)
    return parser.parse_args()


def run_inference(model, data_loader, device):

    model.eval()
    all_main_preds, all_content_preds, all_style_preds, all_fine_grained_preds = [], [], [], []

    all_embeddings = []
    all_true_main_labels = []
    
    with torch.no_grad():
        for batch_data in tqdm(data_loader, desc="  Running Inference"):
            input_ids = batch_data['input_ids'].to(device)
            attention_mask = batch_data['attention_mask'].to(device)
            true_main_labels = batch_data['main_labels'] 


            main_logits, c_logits, s_logits, fg_logits, embeddings = model(input_ids, attention_mask)
            

            all_main_preds.extend(torch.argmax(main_logits, dim=1).cpu().numpy())
            all_content_preds.extend((torch.sigmoid(c_logits) > 0.5).int().cpu().numpy())
            all_style_preds.extend((torch.sigmoid(s_logits) > 0.5).int().cpu().numpy())
            all_fine_grained_preds.extend(torch.argmax(fg_logits, dim=1).cpu().numpy())
            all_embeddings.append(embeddings.cpu().numpy())
            all_true_main_labels.append(true_main_labels.numpy())


    all_embeddings_np = np.concatenate(all_embeddings, axis=0)
    all_true_main_labels_np = np.concatenate(all_true_main_labels, axis=0)

    results = {
        "preds": (all_main_preds, all_content_preds, all_style_preds, all_fine_grained_preds),
        "embeddings": all_embeddings_np,
        "true_labels": all_true_main_labels_np
    }
    return results


def main():
    args = parse_args()
    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    if args.plot_path:
        os.makedirs(os.path.dirname(args.plot_path), exist_ok=True)
        
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  Using device: {device}")


    main_label_map = {"human": 0, "mix": 1, "ai": 2}
    content_label_map = {"human": 0, "qwen25": 1, "qwen3": 2, "llama": 3, "gemini": 4, "gpt4o": 5, "claude": 6, "deepseek": 7}
    style_label_map = {"human": 0, "qwen": 1, "llama": 2, "gemini": 3, "gpt4o": 4, "claude": 5, "deepseek": 6}
    fine_grained_label_map = {"hw": 0, "hwmt": 1, "hwmp": 2, "hwmg": 3, "mg": 4, "mgmp": 5}
    
    idx_to_main_label = {v: k for k, v in main_label_map.items()}
    idx_to_content_label = {v: k for k, v in content_label_map.items()}
    idx_to_style_label = {v: k for k, v in style_label_map.items()}
    idx_to_fine_grained_label = {v: k for k, v in fine_grained_label_map.items()}
    all_label_maps = (main_label_map, content_label_map, style_label_map, fine_grained_label_map)

    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path)
    
    print("  Initializing model architecture...")
    model = MultiTaskMarginModel(
        model_name_or_path=args.model_name_or_path,
        num_main_classes=len(main_label_map), num_content_classes=len(content_label_map),
        num_style_classes=len(style_label_map), num_fine_grained_classes=len(fine_grained_label_map),
        margin_m=args.margin_m, scale_s=args.scale_s, dropout_prob=args.dropout_prob,
        cost_margin=args.cost_margin, human_class_idx=main_label_map["human"], ai_class_idx=main_label_map["ai"]
    ).to(device)

    print(f"  Loading trained weights from: {args.trained_model_path}")
    model.load_state_dict(torch.load(args.trained_model_path, map_location=device))
    
    print(f"  Loading test data from: {args.test_file}")
    test_dataset = InferenceDataset(args.test_file, tokenizer, args.max_len, all_label_maps)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False, num_workers=4)


    results = run_inference(model, test_loader, device)
    (main_preds, content_preds, style_preds, fine_grained_preds) = results["preds"]
    embeddings_to_plot = results["embeddings"]
    true_labels_for_plot = results["true_labels"]
    

    if args.plot_path:
        plot_tsne_visualization(
            embeddings=embeddings_to_plot,
            labels=true_labels_for_plot,
            output_path=args.plot_path,
            label_map=main_label_map
        )
    

    original_data = test_dataset.data
    print(f"\n  Saving results with predictions to: {args.output_file}")
    with open(args.output_file, 'w', encoding='utf-8') as f_out:
        for i, item in enumerate(tqdm(original_data, desc="💾  Saving Results")):
            item['predicted_class'] = idx_to_main_label.get(main_preds[i], "unknown")
            
            content_vector = content_preds[i]
            item['predicted_content_sources'] = [idx_to_content_label[idx] for idx, v in enumerate(content_vector) if v]
            
            style_vector = style_preds[i]
            item['predicted_style_sources'] = [idx_to_style_label[idx] for idx, v in enumerate(style_vector) if v]

            item['predicted_fine_grained_class'] = idx_to_fine_grained_label.get(fine_grained_preds[i], "unknown")
            
            f_out.write(json.dumps(item, ensure_ascii=False) + '\n')
            
    print(f"\n  Inference complete! Output saved to: {args.output_file}")

if __name__ == "__main__":
    main()
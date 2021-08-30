
import torch
from albumentations import *

from model import *
from dataset import *
from utill import * 
from Loss import *
from optimizer import *

from sklearn.metrics import accuracy_score, f1_score
from tqdm import tqdm
import wandb

def train(train_loader, valid_loader, class_weigth, fold_index, config):
    # 모델 생성
    print("Model Generation...")
    model = get_model(config, config.num_classes)
    wandb.watch(model)
    # 모델 정보 출력
    print(model)
    #summary(model, input_size=(3, 512, 384), device=device)

    # 학습
    loss_func = get_loss(config, class_weigth)
    optimizer = get_optimizer(model, config)
    scheduler = get_scheduler(optimizer, config)
    
    best_metric = 0
    best_model_dict = None
    early_stopping_count = 0
    result = {
        'epoch':[],
        'train_loss':[],
        'train_f1':[],
        'valid_loss':[],
        'valid_acc':[],
        'valid_f1':[]
        }
    print("-"*10, "Training", "-"*10)
    for e in range(1, config.epoches + 1):
        batch_loss, batch_f1 = train_per_epoch(train_loader, model, loss_func, optimizer, config)
        running_loss, running_acc, running_f1, examples = vlidation_per_epoch(valid_loader, model, loss_func, config)
        
        # dic로 출력
        result = logging_with_dict(result, e, batch_loss, batch_f1, running_loss, running_acc, running_f1)
        
        # wandb log 출력
        logging_with_wandb(e, batch_loss, batch_f1, running_loss, running_acc, running_f1, examples, fold_index)
        
        # 콘솔 출력
        logging_with_sysprint(e, batch_loss, batch_f1, running_loss, running_acc, running_f1, fold_index)
        
        # lr 스케쥴러 실행
        scheduler.step()

        # f1 score 기준으로 best 모델 채택
        # early_stopping_count 활용
        if running_f1 > best_metric:
            print("-"*10, "Best model changed", "-"*10)
            print("-"*10, "Model_save", "-"*10)
            if fold_index == -1:
                torch.save(model, f'../../models/{config.model_name}/{config.model_name}_{config.config_file_name}_best.pt')
            else:
                torch.save(model, f'../../models/{config.model_name}/fold_{fold_index}_{config.config_file_name}_{config.model_name}_best.pt')
            best_metric = running_f1
            best_model_dict = model.state_dict()
            print("-"*10, "Saved!!", "-"*10)
        else:
            early_stopping_count += 1

        # result dict 저장
        if fold_index == -1:
            pd.DataFrame(result).to_csv(f'../../results/{config.model_name}/{config.model_name}_{config.config_file_name}_result.csv', index=False)
        else:
            pd.DataFrame(result).to_csv(f'../../results/{config.model_name}/fold_{fold_index}_{config.config_file_name}_{config.model_name}_result.csv', index=False)

        if early_stopping_count == config.early_stopping:
            print("-"*10, "Early Stop!!!!", "-"*10)
            break
        
    return best_model_dict

# 1 epoch에 대한 훈련 코드
def train_per_epoch(train_loader, model, loss_func, optimizer, config):
    model.train()
    batch_loss = 0
    batch_f1_pred = []
    batch_f1_target = []
    # train
    for tr_idx, (X, y) in enumerate(tqdm(train_loader)):
        x = X.to(config.device)
        y = y.to(config.device)
        optimizer.zero_grad()

        pred = model.forward(x)
        loss = loss_func(pred, y)
        loss.backward()
        optimizer.step()

        batch_loss += loss.cpu().data
        batch_f1_pred.extend(torch.argmax(pred.cpu().data, dim=1))
        batch_f1_target.extend(y.cpu().data)

    batch_loss /= (tr_idx+1)
    batch_f1 = f1_score(batch_f1_target, batch_f1_pred, average='macro')
    return batch_loss, batch_f1

# 1 epoch에 대한 평가 코드
def vlidation_per_epoch(valid_loader, model, loss_func, config):
     # validation
        model.eval()
        running_acc = 0
        running_loss = 0
        running_f1_pred = []
        running_f1_target = []
        examples = []
        for te_idx, (X, y) in enumerate(tqdm(valid_loader)):
            X = X.to(config.device)
            y = y.to(config.device)

            with torch.set_grad_enabled(False):
                pred = model(X)
                loss = loss_func(pred, y)
                running_acc += accuracy_score(torch.argmax(pred.cpu().data, dim=1), y.cpu().data)
                running_f1_pred.extend(torch.argmax(pred.cpu().data, dim=1))
                running_f1_target.extend(y.cpu().data)
                running_loss += loss.cpu().data
                if te_idx % 10 == 0:
                    pred_label = torch.argmax(pred.cpu().data, dim=1)
                    real_label = y.cpu().data
                    for img_idx in range(config.batch_size):
                        if pred_label[img_idx] != real_label[img_idx]:
                            examples.append(wandb.Image(X[img_idx], caption=f'Pred: {torch.argmax(pred.cpu().data, dim=1)[img_idx]}, Real: {y.cpu().data[img_idx]}'))
        
        running_loss /= (te_idx+1)
        running_acc /= (te_idx+1)
        running_f1 = f1_score(running_f1_target, running_f1_pred, average='macro')

        return running_loss, running_acc, running_f1, examples
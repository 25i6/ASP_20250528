import sys
import logging
import random
import numpy as np

import torch

from torch.optim import AdamW

from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader

import time
from os.path import join
from datetime import datetime

import util
from util.runner import Runner

from metrics import EREEvaluator

torch.cuda.set_device(0)#変更．2025年7月3日．

class NERRunner(Runner):

    def evaluate(self, model, tensor_examples, stored_info, step, predict=False):
        evaluator = EREEvaluator()

        eval_batch_size = 8#16変更．2025年7月3日．
        if any(substr in self.config["plm_pretrained_name_or_path"].lower()\
           for substr in ["pp", "11b", "3b", "xl", "xxl", "large"]):
            eval_batch_size = 8#16変更．2025年7月3日．

        util.runner.logger.info('Step %d: evaluating on %d samples with batch_size %d' % (
            step, len(tensor_examples), eval_batch_size))

        evalloader = DataLoader(
            tensor_examples, batch_size=eval_batch_size, shuffle=False, 
            num_workers=0,
            collate_fn=self.collate_fn, 
            pin_memory=True
        )
        model.eval()
        for i, (doc_keys, tensor_example) in enumerate(evalloader):
            example_gpu = {}

            for k, v in tensor_example.items():
                if v is not None:
                    example_gpu[k] = v.to(self.device)
            example_gpu['is_training'][:] = 0

            with torch.no_grad(), torch.cuda.amp.autocast(
                enabled=self.use_amp, dtype=torch.float16#.bfloat16
            ):
                output = model(**example_gpu)

            for batch_id, doc_key in enumerate(doc_keys):
                gold_res = model.extract_gold_res_from_gold_annotation(
                    {k:v[batch_id] for k, v in tensor_example.items()}, 
                    stored_info['example'][doc_key]
                )
                decoded_results = model.decoding(
                    {k:v[batch_id] for k,v in output.items()}, 
                    stored_info['example'][doc_key]
                )

                decoded_results.update(
                    gold_res
                )
                evaluator.update(
                    **decoded_results
                )
                if predict:
                    util.runner.logger.info(stored_info['example'][doc_key])
                    util.runner.logger.info(decoded_results)

        p,r,f = evaluator.get_prf()
        metrics = {
            'Eval_Ent_Precision': p[0] * 100,
            'Eval_Ent_Recall': r[0] * 100,
            'Eval_Ent_F1': f[0] * 100
        }
        for k,v in metrics.items():
            util.runner.logger.info('%s: %.4f'%(k, v))

        return f[0] * 100, metrics


# python run_ner.py t5_base 0
if __name__ == '__main__':
    config_name, gpu_id = sys.argv[1], int(sys.argv[2])#変更してない．引数0の意味．
    saved_suffix = sys.argv[3] if len(sys.argv) >= 4 else None
    runner = NERRunner(
        config_file="configs/ner.conf",
        config_name=config_name,
        gpu_id=gpu_id
    )

    if saved_suffix is not None:
        model, start_epoch = runner.initialize_model(saved_suffix, continue_training=True)
        runner.train(model, continued=True, start_epoch=start_epoch)
    else:
        model, _ = runner.initialize_model()
        runner.train(model, continued=False)

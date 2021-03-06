import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class Net(nn.Module):
    def __init__(self, params):
        super(Net, self).__init__()
        self.hidden_dim = params.hidden_dim
        self.nb_hops = params.nb_hops
        self.nb_layers = params.nb_layers
        self.embeddings = nn.Embedding(params.vocab_size, params.embedding_dim)
        self.device = params.device

        self.lstm = nn.LSTM(params.embedding_dim, params.hidden_dim, num_layers=params.nb_layers,
                            bidirectional=True, batch_first=True)

        self.ws1 = nn.Linear(2 * params.hidden_dim, params.da, bias=False)
        self.ws2 = nn.Linear(params.da, params.nb_hops, bias=False)

        self.fc = nn.Linear(params.nb_hops * 2 * params.hidden_dim, params.fc_ch)
        self.pred = nn.Linear(params.fc_ch, params.nb_classes)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(p=params.dropout)

    def init_weights(self, init_range=0.1):
        self.embeddings.weight.data.normal_(mean=0, std=1)

    def init_hidden(self, batch_size):
        return (torch.zeros(2 * self.nb_layers, batch_size, self.hidden_dim).to(self.device),
                torch.zeros(2 * self.nb_layers, batch_size, self.hidden_dim).to(self.device))

    def forward(self, inputs, hidden, isDebug=False):
        # n, bsz (n)
        if isDebug: print("inputs size:", inputs.size())

        # n, bsz, embedding_dim (n, d)
        embedded = self.embeddings(inputs)
        if isDebug: print("after embedding:", embedded.size())

        # n, bsz, hidden * 2 () (n, 2u)
        H, (last_hidden_state, last_cell_state) = self.lstm(embedded, hidden)
        if isDebug: print("after lstm: H:", H.size())

        # n, bsz, da
        ws1_out = self.ws1(H)
        tanh_out = F.tanh(ws1_out)
        if isDebug: print("after ws1:", tanh_out.size())

        # n, bsz, hops
        ws2_out = self.ws2(tanh_out)
        if isDebug: print("after ws2:", ws2_out.size())

        bsz, ntk, hops = ws2_out.size()
        tmp = []
        for b in ws2_out:
            tmp.append(F.softmax(b, 0))
        A = torch.stack(tmp)
        if isDebug: print("A:", A.size())

        # bsz, hops, 2u
        M = torch.bmm(H.transpose(1, 2), A)
        if isDebug: print("M:", M.size())

        # encoded output
        fc_outp = self.relu(self.fc(M.view(bsz, -1)))
        if isDebug: print("fc_outp:", fc_outp.size())

        # pred
        dropout_out = self.dropout(fc_outp)
        pred = self.pred(dropout_out)
        if isDebug: print("pred:", pred.size())

        return pred, A, (last_hidden_state, last_cell_state)


def Frobenius(matrix):
    if len(matrix.size()) == 3:
        ret = (torch.sum(torch.sum((matrix ** 2), -1), -1).squeeze() + 1e-10) ** 0.5
        return torch.sum(ret) / matrix.size(0)
    else:
        raise Exception("invalid matrix size for Frobenius function")


def penalization_term(attention, params):
    attention_transposed = attention.transpose(1, 2).contiguous()
    bmm_tmp = torch.bmm(attention, attention_transposed)
    bsz, eye_size, _ = bmm_tmp.size()
    identity_matrix = torch.stack([torch.eye(eye_size)] * bsz).to(params.device)
    p = Frobenius(bmm_tmp - identity_matrix)
    return p * params.coef


def loss_fn(outputs, labels, attention, params):

    loss_cross_entropy = nn.CrossEntropyLoss()
    base_loss = loss_cross_entropy(outputs, labels)

    if not params.isPenalize:
        loss = base_loss
    else:
        extra_loss = penalization_term(attention, params)
        loss = base_loss + extra_loss
    return loss
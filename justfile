build:
    docker build -t atspaeth/organoid-hmm .  

debug: build
    docker run --rm -it atspaeth/organoid-hmm bash

push: build
    docker push atspaeth/organoid-hmm

deploy src exp bin_size ks surrogate="real" method="default":
    #! /usr/bin/env bash
    export HMM_DATA_SOURCE="{{src}}"
    export HMM_EXPERIMENT="{{exp}}"
    export HMM_BIN_SIZE_MS="{{bin_size}}"
    export HMM_K_RANGE="{{ks}}"
    export HMM_SURROGATE="{{surrogate}}"
    export HMM_METHOD="{{method}}"

    if [ "$HMM_EXPERIMENT" = "*" ]; then
        s3dir="s3://braingeneers/personal/atspaeth/data/{{src}}/"
        s3files=$(aws s3 ls "$s3dir" | grep '[^ ]*\.mat' -o)
        for file in $s3files; do
            exp=$(basename "$file" .mat)
            just deploy "{{src}}" "$exp" "{{bin_size}}" "{{ks}}" "{{surrogate}}" "{{method}}" || exit 1
        done

    else
        exp=$(echo $HMM_EXPERIMENT | tr '_[:upper:]\,' '-[:lower:].')
        stamp=$(printf '%(%m%d%H%M%S)T\n' -1)
        export JOB_NAME=atspaeth-hmms-$stamp-$exp
        envsubst < job.yml | kubectl apply -f -
    fi

split-deploy src exp splits surrogate="real" method="default":
    #! /usr/bin/env bash
    for i in $(seq 0 $(({{splits}} - 1))); do
        start=$((10 + (41 * i) / {{splits}}))
        end=$((9 + (41 * (i + 1)) / {{splits}}))
        just deploy "{{src}}" "{{exp}}" 30 "$start-$end" "{{surrogate}}" "{{method}}" || exit 1
    done

local src exp bin_size ks surrogate="real" method="default":
    python stash_hmms.py {{src}} {{exp}} {{bin_size}} {{ks}} {{surrogate}} {{method}}
